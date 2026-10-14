"""
Localisation for notification templates and status labels.

Templates use str.format placeholders. Numbers (prices, quantities) are passed in already
formatted so the agreed terms are shown exactly as stored, whatever the language.
"""
SUPPORTED_LANGUAGES = ("en", "te")
DEFAULT_LANGUAGE = "en"

TEMPLATES: dict[str, dict[str, tuple[str, str]]] = {
    "en": {
        "offer_received": ("New offer received", "{party} offered ₹{price}/{unit} for {quantity} {unit} of {crop}."),
        "offer_countered": ("Counteroffer received", "{party} countered at ₹{price}/{unit} for {quantity} {unit} of {crop}."),
        "offer_accepted": ("Offer accepted", "Your offer for {crop} was accepted. Order {order_number} created."),
        "offer_rejected": ("Offer rejected", "{party} rejected your offer for {crop}."),
        "offer_withdrawn": ("Offer withdrawn", "{party} withdrew their offer for {crop}."),
        "offer_expiring": ("Offer expiring soon", "The offer for {crop} expires at {expires_at} UTC."),
        "offer_expired": ("Offer expired", "The offer for {crop} has expired. You can send a new offer."),
        "negotiation_cancelled": ("Negotiation cancelled", "{party} cancelled the negotiation for {crop}."),
        "order_created": ("New order", "Order {order_number}: {quantity} {unit} of {crop} at ₹{price}/{unit}. Please confirm."),
        "order_confirmed": ("Order confirmed", "Order {order_number} is confirmed."),
        "order_status": ("Order update", "Order {order_number} is now {status}."),
        "order_cancelled": ("Order cancelled", "Order {order_number} was cancelled. Reason: {reason}"),
        "order_cancel_requested": ("Cancellation requested", "{party} requested to cancel order {order_number}: {reason}"),
        "order_ready": ("Ready for pickup", "Order {order_number} is ready for pickup."),
        "delivery_code": ("Delivery code", "Share code {code} with the farmer only when you receive order {order_number}."),
        "order_delivered": ("Order delivered", "Order {order_number} was marked delivered."),
        "order_completed": ("Order completed", "Order {order_number} is complete. You can now rate the other party."),
        "payment_received": ("Payment received", "₹{amount} received for order {order_number}."),
        "payment_failed": ("Payment failed", "A payment of ₹{amount} for order {order_number} failed."),
        "payment_reminder": ("Payment reminder", "₹{amount} is outstanding for order {order_number}."),
        "cash_recorded": ("Cash payment recorded", "The farmer recorded ₹{amount} received in cash for order {order_number}."),
        "refund_status": ("Refund update", "Refund of ₹{amount} for order {order_number} is {status}."),
        "settlement_paid": ("Payout sent", "₹{amount} was paid out for order {order_number}."),
        "pickup_scheduled": ("Pickup scheduled", "Pickup for order {order_number} is scheduled on {date}."),
        "listing_expiring": ("Listing expiring soon", "Your {crop} listing expires on {date}."),
        "listing_expired": ("Listing expired", "Your {crop} listing has expired."),
        "low_stock": ("Low stock", "Only {quantity} {unit} of {crop} left in your listing."),
        "saved_listing_price_change": ("Price changed", "{crop} from {party} is now ₹{price}/{unit} (was ₹{old_price})."),
        "crop_alert_match": ("New listing matches your alert", "{quantity} {unit} of {crop} at ₹{price}/{unit} from {party}."),
        "favourite_new_stock": ("New stock from a saved farmer", "{party} listed {quantity} {unit} of {crop} at ₹{price}/{unit}."),
        "price_change_alert": ("Market price moved", "Average {crop} deal price changed {change}% this week (now ₹{price}/{unit})."),
        "new_message": ("New message from {party}", "{preview}"),
        "review_received": ("New review", "You received a {rating}★ review."),
        "review_response": ("Reply to your review", "{party} replied to your review."),
        "dispute_raised": ("Dispute raised", "A dispute was raised on order {order_number}: {reason}."),
        "dispute_update": ("Dispute update", "Dispute #{dispute_id} is now {status}."),
        "dispute_resolved": ("Dispute closed", "Dispute #{dispute_id} was {status}: {resolution}"),
        "verification_update": ("Verification update", "Your {kind} verification is {status}."),
        "account_status": ("Account update", "Your account is now {status}. {reason}"),
        "buy_request_invite": ("Quote requested", "{party} invited you to quote for {quantity} {unit} of {crop}."),
        "buy_response_received": ("New quotation", "A farmer quoted ₹{price}/{unit} for {quantity} {unit} of {crop}."),
        "buy_response_accepted": ("Quotation accepted", "Your quotation was accepted. Order {order_number} created."),
        "buy_response_rejected": ("Quotation declined", "The vendor declined your quotation for {crop}."),
        "recurring_proposed": ("Recurring supply proposed", "{party} proposed {quantity} {unit} of {crop} {frequency} at ₹{price}/{unit}."),
        "recurring_update": ("Recurring supply update", "Recurring supply #{recurring_id} is now {status}."),
        "recurring_skipped": ("Recurring order skipped", "Not enough {crop} stock for recurring supply #{recurring_id}."),
        "ticket_update": ("Support ticket update", "Ticket #{ticket_id}: {status}."),
        "announcement": ("{title}", "{body}"),
        "order_adjustment": ("Order amount corrected", "Order {order_number} was adjusted by ₹{amount}: {reason}"),
        "listing_moderated": ("Listing update", "Your {crop} listing was {status}. {reason}"),
        "agent_approval_needed": ("Approval needed", "Your assistant is waiting for your approval: {summary}"),
        "agent_update": ("Assistant update", "{summary}"),
    },
    "te": {
        "offer_received": ("కొత్త ఆఫర్ వచ్చింది", "{party} {crop} {quantity} {unit} కు ₹{price}/{unit} ఆఫర్ చేశారు."),
        "offer_countered": ("కౌంటర్ ఆఫర్ వచ్చింది", "{party} {crop} {quantity} {unit} కు ₹{price}/{unit} కౌంటర్ చేశారు."),
        "offer_accepted": ("ఆఫర్ అంగీకరించబడింది", "{crop} కోసం మీ ఆఫర్ అంగీకరించబడింది. ఆర్డర్ {order_number} సృష్టించబడింది."),
        "offer_rejected": ("ఆఫర్ తిరస్కరించబడింది", "{party} {crop} కోసం మీ ఆఫర్‌ను తిరస్కరించారు."),
        "offer_withdrawn": ("ఆఫర్ ఉపసంహరించబడింది", "{party} {crop} ఆఫర్‌ను ఉపసంహరించుకున్నారు."),
        "offer_expiring": ("ఆఫర్ త్వరలో ముగుస్తుంది", "{crop} ఆఫర్ {expires_at} UTC కి ముగుస్తుంది."),
        "offer_expired": ("ఆఫర్ గడువు ముగిసింది", "{crop} ఆఫర్ గడువు ముగిసింది. మీరు కొత్త ఆఫర్ పంపవచ్చు."),
        "negotiation_cancelled": ("బేరం రద్దు", "{party} {crop} బేరాన్ని రద్దు చేశారు."),
        "order_created": ("కొత్త ఆర్డర్", "ఆర్డర్ {order_number}: {crop} {quantity} {unit}, ₹{price}/{unit}. దయచేసి నిర్ధారించండి."),
        "order_confirmed": ("ఆర్డర్ నిర్ధారించబడింది", "ఆర్డర్ {order_number} నిర్ధారించబడింది."),
        "order_status": ("ఆర్డర్ అప్‌డేట్", "ఆర్డర్ {order_number} ఇప్పుడు {status}."),
        "order_cancelled": ("ఆర్డర్ రద్దు", "ఆర్డర్ {order_number} రద్దు చేయబడింది. కారణం: {reason}"),
        "order_cancel_requested": ("రద్దు అభ్యర్థన", "{party} ఆర్డర్ {order_number} రద్దు కోరారు: {reason}"),
        "order_ready": ("పికప్‌కు సిద్ధం", "ఆర్డర్ {order_number} పికప్‌కు సిద్ధంగా ఉంది."),
        "delivery_code": ("డెలివరీ కోడ్", "ఆర్డర్ {order_number} అందిన తర్వాతే రైతుకు కోడ్ {code} చెప్పండి."),
        "order_delivered": ("ఆర్డర్ డెలివరీ అయింది", "ఆర్డర్ {order_number} డెలివరీ అయినట్లు నమోదైంది."),
        "order_completed": ("ఆర్డర్ పూర్తయింది", "ఆర్డర్ {order_number} పూర్తయింది. ఇప్పుడు రేటింగ్ ఇవ్వవచ్చు."),
        "payment_received": ("చెల్లింపు అందింది", "ఆర్డర్ {order_number} కోసం ₹{amount} అందింది."),
        "payment_failed": ("చెల్లింపు విఫలమైంది", "ఆర్డర్ {order_number} కోసం ₹{amount} చెల్లింపు విఫలమైంది."),
        "payment_reminder": ("చెల్లింపు గుర్తు", "ఆర్డర్ {order_number} కోసం ₹{amount} బాకీ ఉంది."),
        "cash_recorded": ("నగదు చెల్లింపు నమోదు", "ఆర్డర్ {order_number} కోసం రైతు ₹{amount} నగదు అందినట్లు నమోదు చేశారు."),
        "refund_status": ("రీఫండ్ అప్‌డేట్", "ఆర్డర్ {order_number} కోసం ₹{amount} రీఫండ్ {status}."),
        "settlement_paid": ("చెల్లింపు పంపబడింది", "ఆర్డర్ {order_number} కోసం ₹{amount} చెల్లించబడింది."),
        "pickup_scheduled": ("పికప్ షెడ్యూల్", "ఆర్డర్ {order_number} పికప్ {date} న."),
        "listing_expiring": ("లిస్టింగ్ త్వరలో ముగుస్తుంది", "మీ {crop} లిస్టింగ్ {date} న ముగుస్తుంది."),
        "listing_expired": ("లిస్టింగ్ గడువు ముగిసింది", "మీ {crop} లిస్టింగ్ గడువు ముగిసింది."),
        "low_stock": ("స్టాక్ తక్కువగా ఉంది", "మీ లిస్టింగ్‌లో {crop} {quantity} {unit} మాత్రమే మిగిలి ఉంది."),
        "saved_listing_price_change": ("ధర మారింది", "{party} నుండి {crop} ఇప్పుడు ₹{price}/{unit} (ముందు ₹{old_price})."),
        "crop_alert_match": ("మీ అలర్ట్‌కు సరిపోయే లిస్టింగ్", "{party} నుండి {crop} {quantity} {unit}, ₹{price}/{unit}."),
        "favourite_new_stock": ("సేవ్ చేసిన రైతు నుండి కొత్త స్టాక్", "{party} {crop} {quantity} {unit} ₹{price}/{unit} కు లిస్ట్ చేశారు."),
        "price_change_alert": ("మార్కెట్ ధర మారింది", "ఈ వారం {crop} సగటు ధర {change}% మారింది (ఇప్పుడు ₹{price}/{unit})."),
        "new_message": ("{party} నుండి కొత్త సందేశం", "{preview}"),
        "review_received": ("కొత్త సమీక్ష", "మీకు {rating}★ సమీక్ష వచ్చింది."),
        "review_response": ("మీ సమీక్షకు జవాబు", "{party} మీ సమీక్షకు జవాబు ఇచ్చారు."),
        "dispute_raised": ("వివాదం నమోదైంది", "ఆర్డర్ {order_number} పై వివాదం: {reason}."),
        "dispute_update": ("వివాదం అప్‌డేట్", "వివాదం #{dispute_id} ఇప్పుడు {status}."),
        "dispute_resolved": ("వివాదం ముగిసింది", "వివాదం #{dispute_id} {status}: {resolution}"),
        "verification_update": ("ధృవీకరణ అప్‌డేట్", "మీ {kind} ధృవీకరణ {status}."),
        "account_status": ("ఖాతా అప్‌డేట్", "మీ ఖాతా ఇప్పుడు {status}. {reason}"),
        "buy_request_invite": ("కొటేషన్ అభ్యర్థన", "{party} {crop} {quantity} {unit} కోసం కొటేషన్ కోరారు."),
        "buy_response_received": ("కొత్త కొటేషన్", "ఒక రైతు {crop} {quantity} {unit} కు ₹{price}/{unit} కోట్ చేశారు."),
        "buy_response_accepted": ("కొటేషన్ అంగీకరించబడింది", "మీ కొటేషన్ అంగీకరించబడింది. ఆర్డర్ {order_number}."),
        "buy_response_rejected": ("కొటేషన్ తిరస్కరణ", "{crop} కోసం మీ కొటేషన్‌ను వ్యాపారి తిరస్కరించారు."),
        "recurring_proposed": ("పునరావృత సరఫరా ప్రతిపాదన", "{party} {crop} {quantity} {unit} {frequency} ₹{price}/{unit} కు ప్రతిపాదించారు."),
        "recurring_update": ("పునరావృత సరఫరా అప్‌డేట్", "పునరావృత సరఫరా #{recurring_id} ఇప్పుడు {status}."),
        "recurring_skipped": ("పునరావృత ఆర్డర్ దాటవేయబడింది", "పునరావృత సరఫరా #{recurring_id} కోసం {crop} స్టాక్ సరిపోలేదు."),
        "ticket_update": ("సపోర్ట్ టికెట్ అప్‌డేట్", "టికెట్ #{ticket_id}: {status}."),
        "announcement": ("{title}", "{body}"),
        "order_adjustment": ("ఆర్డర్ మొత్తం సవరణ", "ఆర్డర్ {order_number} ₹{amount} సవరించబడింది: {reason}"),
        "listing_moderated": ("లిస్టింగ్ అప్‌డేట్", "మీ {crop} లిస్టింగ్ {status}. {reason}"),
        "agent_approval_needed": ("ఆమోదం అవసరం", "మీ అసిస్టెంట్ మీ ఆమోదం కోసం వేచి ఉంది: {summary}"),
        "agent_update": ("అసిస్టెంట్ అప్‌డేట్", "{summary}"),
    },
}

STATUS_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "pending_confirmation": "Pending confirmation", "confirmed": "Confirmed", "preparing": "Preparing",
        "ready_for_pickup": "Ready for pickup", "in_transit": "In transit", "delivered": "Delivered",
        "completed": "Completed", "cancelled": "Cancelled", "delivery_failed": "Delivery failed",
        "disputed": "Disputed", "refund_pending": "Refund pending", "refunded": "Refunded",
        "DRAFT": "Draft", "PENDING": "Pending", "COUNTERED": "Countered", "ACCEPTED": "Accepted",
        "REJECTED": "Rejected", "WITHDRAWN": "Withdrawn", "EXPIRED": "Expired", "CANCELLED": "Cancelled",
        "OPEN": "Open", "verified": "verified", "rejected": "rejected",
        "VERIFIED": "verified", "PENDING_VERIFICATION": "pending review",
        "weekly": "weekly", "biweekly": "every two weeks", "monthly": "monthly",
    },
    "te": {
        "pending_confirmation": "నిర్ధారణ కోసం వేచి ఉంది", "confirmed": "నిర్ధారించబడింది", "preparing": "సిద్ధం చేస్తున్నారు",
        "ready_for_pickup": "పికప్‌కు సిద్ధం", "in_transit": "రవాణాలో ఉంది", "delivered": "డెలివరీ అయింది",
        "completed": "పూర్తయింది", "cancelled": "రద్దు చేయబడింది", "delivery_failed": "డెలివరీ విఫలమైంది",
        "disputed": "వివాదంలో ఉంది", "refund_pending": "రీఫండ్ పెండింగ్", "refunded": "రీఫండ్ అయింది",
        "DRAFT": "డ్రాఫ్ట్", "PENDING": "పెండింగ్", "COUNTERED": "కౌంటర్ చేయబడింది", "ACCEPTED": "అంగీకరించబడింది",
        "REJECTED": "తిరస్కరించబడింది", "WITHDRAWN": "ఉపసంహరించబడింది", "EXPIRED": "గడువు ముగిసింది", "CANCELLED": "రద్దు",
        "OPEN": "తెరిచి ఉంది", "verified": "ధృవీకరించబడింది", "rejected": "తిరస్కరించబడింది",
        "VERIFIED": "ధృవీకరించబడింది", "PENDING_VERIFICATION": "సమీక్షలో ఉంది",
        "weekly": "వారానికి", "biweekly": "రెండు వారాలకు", "monthly": "నెలకు",
    },
}


class _SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def normalize_language(lang: str | None) -> str:
    if not lang:
        return DEFAULT_LANGUAGE
    lang = lang.split(",")[0].split("-")[0].strip().lower()
    return lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def status_label(status: str | None, lang: str = DEFAULT_LANGUAGE) -> str | None:
    if status is None:
        return None
    lang = normalize_language(lang)
    return STATUS_LABELS[lang].get(status) or STATUS_LABELS[DEFAULT_LANGUAGE].get(status) or status


def render(template_key: str, lang: str, **params) -> tuple[str, str]:
    lang = normalize_language(lang)
    template = TEMPLATES[lang].get(template_key) or TEMPLATES[DEFAULT_LANGUAGE][template_key]
    if "status" in params:
        params["status"] = status_label(str(params["status"]), lang)
    if "frequency" in params:
        params["frequency"] = status_label(str(params["frequency"]), lang)
    values = _SafeDict({k: ("" if v is None else v) for k, v in params.items()})
    title, message = template
    return title.format_map(values)[:120], message.format_map(values)[:500]
