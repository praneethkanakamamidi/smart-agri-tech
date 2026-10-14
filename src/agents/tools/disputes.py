"""
Evidence, image analysis and dispute tools.

retrieve_evidence only returns records the caller may already see (participants never get admin
internal notes). Every record gets a stable reference id; investigation reports may only cite
these ids. resolve_dispute runs with an admin's authority after that admin approves it.
"""
from datetime import datetime

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.config import settings
from src.agents.context import RunContext
from src.agents.domain.quality import VISION_SYSTEM_PROMPT, ProduceQualityAssessment, postprocess, unavailable_result
from src.agents.llm import Message, TaskType
from src.agents.llm.errors import LLMError, NoCapableModel
from src.agents.llm.types import ImagePart
from src.agents.policy import UNTRUSTED_DATA_RULES, wrap_untrusted
from src.agents.tools.base import tool
from src.agents.vision import ImageRejected, prepare_image
from src.core.storage import storage
from src.data_models.agents_model import DisputeInvestigationReports
from src.data_models.disputes_model import DisputeMessages
from src.data_models.logistics_model import Shipments
from src.data_models.negotiation_model import Offers
from src.data_models.orders_model import Orders, OrderStatusHistory
from src.data_models.platform_model import StoredFiles
from src.data_models.users_model import Users
from src.schemas.disputes_schema import ResolveDisputeSchema
from src.security_utils.role_guard import ADMIN
from src.services import order_core
from src.services.disputes_service import DisputesService
from src.services.files_service import FilesService, IMAGES

TERM_FIELDS = ("quantity", "unit", "unit_price", "subtotal", "total_payable", "fulfillment_mode", "payment_terms",
               "expected_delivery_date", "delivery_instructions", "packaging_spec", "quality_spec", "offer_version",
               "agreed_at", "produce")


def _role_of(user_id, order: Orders) -> str:
    return "farmer" if user_id == order.farmer else "vendor" if user_id == order.vendor else "admin" if user_id else "system"


class DisputeRef(BaseModel):
    dispute_id: int = Field(..., gt=0)


@tool("retrieve_evidence", DisputeRef,
      "Every record relevant to a dispute the caller may see, each with a reference id for citations.")
async def retrieve_evidence(db: AsyncSession, actor: Users, args: DisputeRef, ctx: RunContext) -> dict:
    is_admin = actor.role_name == ADMIN
    case = await DisputesService().get(args.dispute_id, actor.id, is_admin, db)  # 404 unless party or admin
    order = (await db.execute(select(Orders).where(Orders.id == case["order_id"]))).scalar_one()
    refs: dict[str, dict] = {}
    refs[f"dispute:{case['id']}"] = {"kind": "complaint", "data": {
        "reason": case["reason"], "description": case.get("description"), "status": case["status"],
        "raised_by_role": _role_of(case["raised_by"], order), "created_at": case.get("created_at"),
    }}
    file_ids: list[str] = []
    for message in case.get("history", []):
        refs[f"dispute_message:{message['id']}"] = {"kind": message.get("kind"), "data": {
            "author_role": _role_of(message.get("author_id"), order), "body": message.get("body"),
            "file_ids": message.get("file_ids") or [], "created_at": message.get("created_at"),
        }}
        file_ids += message.get("file_ids") or []
    snapshot = order.terms_snapshot or {}
    refs[f"order:{order.id}#terms"] = {"kind": "agreed_terms", "data": {
        "order_number": order.order_number, **{k: snapshot.get(k) for k in TERM_FIELDS if k in snapshot},
    }}
    history = (await db.execute(select(OrderStatusHistory).where(OrderStatusHistory.order_id == order.id)
                                .order_by(OrderStatusHistory.id))).scalars().all()
    refs[f"order:{order.id}#timeline"] = {"kind": "status_history", "data": [
        {"from": h.from_status, "to": h.to_status, "at": h.created_at, "by": _role_of(h.actor_id, order), "note": h.note}
        for h in history
    ]}
    if order.negotiation_id:
        offers = (await db.execute(select(Offers).where(Offers.negotiation_id == order.negotiation_id,
                                                        Offers.status != "DRAFT").order_by(Offers.version))).scalars().all()
        for offer in offers:
            refs[f"offer:{offer.id}"] = {"kind": "offer", "data": {
                "version": offer.version, "by": offer.offered_by_role, "quantity": offer.quantity, "unit": offer.unit,
                "unit_price": offer.unit_price, "quality_spec": offer.quality_spec, "packaging": offer.packaging,
                "status": offer.status, "created_at": offer.created_at,
            }}
    shipment = (await db.execute(select(Shipments).where(Shipments.order_id == order.id))).scalar_one_or_none()
    if shipment:
        refs[f"shipment:{shipment.id}"] = {"kind": "delivery_record", "data": {
            "mode": shipment.mode, "status": shipment.status, "pickup_date": shipment.pickup_date,
            "dispatched_at": shipment.dispatched_at, "delivered_at": shipment.delivered_at,
            "accepted_quantity": shipment.accepted_quantity, "quality_accepted": shipment.quality_accepted,
            "receiver_name_recorded": bool(shipment.receiver_name), "delivery_notes": shipment.delivery_notes,
            "failure_reason": shipment.failure_reason, "reschedule_count": shipment.reschedule_count,
            "pickup_proof_file_id": shipment.pickup_proof_file_id, "delivery_proof_file_id": shipment.delivery_proof_file_id,
        }}
        file_ids += [f for f in (shipment.pickup_proof_file_id, shipment.delivery_proof_file_id) if f]
    refs[f"payments:{order.id}"] = {"kind": "payments", "data": await order_core.money_summary(db, order)}
    if file_ids:
        files = (await db.execute(select(StoredFiles).where(StoredFiles.id.in_(set(file_ids)),
                                                            StoredFiles.deleted_at.is_(None)))).scalars().all()
        for f in files:
            refs[f"file:{f.id}"] = {"kind": "uploaded_file", "data": {
                "content_type": f.content_type, "purpose": f.purpose, "uploaded_by_role": _role_of(f.owner_id, order),
                "size_bytes": f.size_bytes, "sha256": f.sha256, "uploaded_at": f.created_at,
            }}
    return {"dispute_id": case["id"], "order_id": order.id, "reason": case["reason"], "status": case["status"],
            "refs": refs, "ref_ids": sorted(refs)}


class ImageAnalysisInput(BaseModel):
    file_id: str = Field(..., min_length=36, max_length=36)
    commodity_hint: str | None = Field(None, max_length=60, description="What the uploader says it is (untrusted).")


@tool("analyze_produce_image", ImageAnalysisInput,
      "Visual assessment of a produce photo by a vision-capable model, with uncertainty and limitations.")
async def analyze_produce_image(db: AsyncSession, actor: Users, args: ImageAnalysisInput, ctx: RunContext) -> dict:
    f = (await db.execute(select(StoredFiles).where(StoredFiles.id == args.file_id,
                                                    StoredFiles.deleted_at.is_(None)))).scalar_one_or_none()
    if not f or not await FilesService()._can_access(actor, actor.role_name, f, db):
        raise HTTPException(status_code=404, detail="File not found.")
    if f.content_type not in IMAGES:
        raise HTTPException(status_code=415, detail="Only JPEG, PNG or WebP photos can be analysed.")
    try:
        content = storage.read(f.storage_path)
        image, media_type, dims = await prepare_image(content, settings().vision_max_edge_px)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File content is missing.")
    except ImageRejected as e:
        raise HTTPException(status_code=422, detail=str(e))
    router = ctx.llm
    prompt = "Assess the produce in this photo." + (
        "\n" + wrap_untrusted("uploader_hint", f"The uploader says this is: {args.commodity_hint}")
        if args.commodity_hint else "")
    try:
        assessment, response = await router.structured(
            TaskType.IMAGE_UNDERSTANDING, ProduceQualityAssessment,
            [Message.user(prompt, ImagePart(image, media_type))],
            system=VISION_SYSTEM_PROMPT + "\n" + UNTRUSTED_DATA_RULES, run_id=ctx.run_id, user_id=actor.id,
        )
    except NoCapableModel:
        return {"file_id": f.id, **unavailable_result("No vision-capable model is configured.")}
    except LLMError as e:
        return {"file_id": f.id, **unavailable_result(f"Vision analysis failed ({e.code}).")}
    return {"file_id": f.id, "analysis_available": True, **postprocess(assessment),
            "model": {"id": response.model_id, "provider": response.provider}, "image": dims}


class DisputeReportInput(BaseModel):
    dispute_id: int = Field(..., gt=0)
    report: dict
    evidence_index: dict
    generated_by: str = Field(..., max_length=60)


@tool("create_dispute_report", DisputeReportInput, "Store the investigation report for admin review (no decision).")
async def create_dispute_report(db: AsyncSession, actor: Users, args: DisputeReportInput, ctx: RunContext) -> dict:
    await DisputesService().get(args.dispute_id, actor.id, actor.role_name == ADMIN, db)  # access check
    if ctx.run_id:
        existing = (await db.execute(select(DisputeInvestigationReports).where(
            DisputeInvestigationReports.dispute_id == args.dispute_id,
            DisputeInvestigationReports.run_id == ctx.run_id))).scalar_one_or_none()
        if existing:
            return {"report_id": existing.id, "status": existing.status, "created": False}
    now = datetime.utcnow()
    report = DisputeInvestigationReports(
        dispute_id=args.dispute_id, run_id=ctx.run_id, status="pending_review", report=args.report,
        evidence_index=args.evidence_index, generated_by=args.generated_by, requires_human_review=True, created_at=now,
    )
    db.add(report)
    await db.flush()
    db.add(DisputeMessages(
        dispute_id=args.dispute_id, author_id=None, kind="internal_note", file_ids=[], created_at=now,
        body=(f"Assistant investigation report #{report.id} is ready for review "
              f"(severity: {args.report.get('severity', 'unknown')}). It does not decide the case."),
    ))
    return {"report_id": report.id, "status": report.status, "created": True}


class ResolveDisputeInput(ResolveDisputeSchema):
    dispute_id: int = Field(..., gt=0)
    report_id: int | None = Field(None, gt=0)


@tool("resolve_dispute", ResolveDisputeInput, "Record an admin's decision on a dispute. Admin approval required.")
async def resolve_dispute(db: AsyncSession, actor: Users, args: ResolveDisputeInput, ctx: RunContext) -> dict:
    payload = ResolveDisputeSchema(**args.model_dump(include={"status", "resolution", "resolution_type", "refund_amount"}))
    result = await DisputesService().resolve_dispute(args.dispute_id, payload, actor.id, db)
    if args.report_id:
        report = await db.get(DisputeInvestigationReports, args.report_id)
        if report and report.dispute_id == args.dispute_id:
            report.status, report.reviewed_by, report.reviewed_at = "reviewed", actor.id, datetime.utcnow()
            report.review_decision = f"{args.status}:{args.resolution_type}"
    return {**result, "dispute_id": args.dispute_id}
