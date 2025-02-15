from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from src.data_models.miscellaneous_model import Miscellaneous_Data
from src.data_models.role_permissions import RolePermissions
from src.data_models.permissions_model import Permissions

class PermissionsService:
    def get_permissions(self, role_id: int, db: Session) -> list:
        """
        Retrieves the permissions for a given role.

        Args:
            role_id (int): The ID of the role whose permissions need to be fetched.
            db (Session): The database session used to execute queries.

        Returns:
            list: A list containing dictionaries of permissions for the role.

        Raises:
            HTTPException: Returns a 500 Internal Server Error if an exception occurs.
        """
        try:
            # Fetch miscellaneous data where category = 'answer' and value = 'yes' (case-insensitive)
            miscellaneous_data = db.query(Miscellaneous_Data).filter(
                func.lower(Miscellaneous_Data.category).ilike("answer"),
                func.lower(Miscellaneous_Data.value).ilike("yes")
            ).first()

            # Fetch role permissions for the given role_id
            role_permissions = (
                db.query(RolePermissions)
                .filter(RolePermissions.role_id == role_id)
                .order_by(RolePermissions.id)
                .all()
            )

            permissions = []

            # Iterate through each role_permission entry
            for role_permission in role_permissions:
                # Fetch permission details using permission_id
                permission = db.query(Permissions).filter(Permissions.id == role_permission.permission_id).first()
                if not permission:
                    continue  # Skip if permission does not exist

                # Initialize permission object with module name
                permission_object = {
                    "permission_name": permission.permission_name,
                    "permission_key": permission.permission_key,
                    "access": []
                }

                # Map access rights based on miscellaneous_data
                if miscellaneous_data and role_permission.can_read == miscellaneous_data.id:
                    permission_object["access"].append("can_read")
                if miscellaneous_data and role_permission.can_write == miscellaneous_data.id:
                    permission_object["access"].append("can_write")
                if miscellaneous_data and role_permission.can_delete == miscellaneous_data.id:
                    permission_object["access"].append("can_delete")

                # Store permission object in list
                permissions.append(permission_object)

            return permissions

        except Exception as e:
            db.rollback()  # Rollback transaction in case of an error
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"An error occurred: {str(e)}"
            )
