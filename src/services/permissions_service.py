from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.data_models.role_permissions import RolePermissions
from src.data_models.permissions_model import Permissions


class PermissionsService:
    async def get_permissions(self, role_id: int, db: AsyncSession) -> list:
        try:
            stmt_misc = select(Miscellaneous_Data).where(
                Miscellaneous_Data.category.ilike("answer"),
                Miscellaneous_Data.value.ilike("yes"),
            )
            res_misc = await db.execute(stmt_misc)
            miscellaneous_data = res_misc.scalar_one_or_none()

            stmt_rp = (
                select(RolePermissions)
                .where(RolePermissions.role_id == role_id)
                .order_by(RolePermissions.id)
            )
            res_rp = await db.execute(stmt_rp)
            role_permissions = res_rp.scalars().all()

            permissions = []
            for role_permission in role_permissions:
                stmt_perm = select(Permissions).where(
                    Permissions.id == role_permission.permission_id
                )
                res_perm = await db.execute(stmt_perm)
                permission = res_perm.scalar_one_or_none()
                if not permission:
                    continue

                permission_object = {
                    "permission_name": permission.permission_name,
                    "permission_key": permission.permission_key,
                    "access": [],
                }
                if miscellaneous_data and role_permission.can_read == miscellaneous_data.id:
                    permission_object["access"].append("can_read")
                if miscellaneous_data and role_permission.can_write == miscellaneous_data.id:
                    permission_object["access"].append("can_write")
                if miscellaneous_data and role_permission.can_delete == miscellaneous_data.id:
                    permission_object["access"].append("can_delete")
                permissions.append(permission_object)

            return permissions
        except Exception as e:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}",
            )
