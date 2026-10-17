from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.auth.schemas import LoginRequest, ChangePasswordRequest
from app.schemas.user import UserCreate, UserUpdate

from app.auth.security import (
    verify_password, 
    create_access_token, 
    create_refresh_token, 
    decode_access_token,
    decode_refresh_token,
    hash_password
) 

from app.auth.dependencies import (
    get_current_user, 
    get_current_admin,
)

from app.auth.user_service import (
    get_user_by_username, 
    get_user_by_id, 
    get_all_users,
    create_user,
    update_user,
    update_user_status,
    delete_user,
)

from jose import JWTError
from app import database

router = APIRouter(
    prefix='/api/auth',
    tags=['Authentication']
)

# LOGIN

@router.post('/login')
async def login(login_data: LoginRequest):

    user = await get_user_by_username(login_data.username)

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid Username or password"
        )

    # Inactive users cant log in
    if not user["is_active"]:
            raise HTTPException(
                status_code=403,
                detail="User account is inactive"
            )
        
    password_valid = verify_password(
        login_data.password, 
        user["hashed_password"]
    )    

    if not password_valid:
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )
    
    # Access token contains current token generation
    access_token = create_access_token(
        {
            "sub":str(user["id"]),
            "token_gen":user["token_gen"],
        }
    )

    # Refresh token also contains current token generation
    refresh_token = create_refresh_token(
        {
            "sub":str(user["id"]),
            "token_gen":user["token_gen"]
        }
    )

    return{
        "access_token":access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


# Home
@router.get("/home")
async def home(current_user: dict = Depends(get_current_user)):
    return{
        "message":"Welcome to TDAC",
        "user": {
            "id": current_user["id"],
            "username":current_user["username"],
            "role":current_user["role_name"]
        }
    }

# Admin Test
@router.get("/admin-test")
async def admin_test(
    current_admin: dict = Depends(get_current_admin)
):
    return{
        "message":"Welcome Admin",
        "user":current_admin
    }

# Refresh Access Token
class RefreshRequest(BaseModel):
    """Refresh token in a JSON body, not a query parameter.

    A query string lands in access logs, proxy logs, and browser history.
    A long-lived credential does not belong in any of those.
    """

    refresh_token: str


@router.post("/refresh")
async def refresh_access_token(body: RefreshRequest):

    try:
        payload = decode_refresh_token(body.refresh_token)

    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired refresh token"
        )

    user_id = payload.get("sub")

    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid refresh token"
        )

    try:
        user_id = int(user_id)

    except (TypeError, ValueError):
        print("INVALID USER ID:", user_id)

        raise HTTPException(
            status_code=401,
            detail="Invalid refresh token"
        )

    user = await get_user_by_id(user_id)

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="User no longer exists"
        )

    # Inactive accounts cannot refresh tokens
    if not user['is_active']:
        raise HTTPException(
            status_code=403,
            detail="User account is inactive"
        )

    # Token generation must match the database
    if user["token_gen"] != payload.get("token_gen"):
        raise HTTPException(
            status_code=401,
            detail="Refresh token has been invalidated"
        )
    # Create a new access token using the current token generation
    new_access_token = create_access_token(
        {
            "sub": str(user["id"]),
            "token_gen":user["token_gen"],
        }
    )

    return {
        "access_token": new_access_token,
        "token_type": "bearer"
    }

# Change Password (self-service, from the Topbar account menu)
@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    if body.new_password == body.current_password:
        raise HTTPException(
            status_code=400,
            detail="New password must differ from the current one"
        )

    # The bearer token already proved the session, but the password is
    # re-verified so a stolen token cannot silently take over the account.
    if not verify_password(
        body.current_password,
        current_user["hashed_password"],
    ):
        raise HTTPException(
            status_code=401,
            detail="Current password is incorrect"
        )

    # Bumping token_gen revokes every session. Fresh tokens with the new
    # gen are returned so THIS session survives while all others die.
    new_token_gen = current_user["token_gen"] + 1

    hashed_password = hash_password(body.new_password)

    await database.pool.execute(
        """
        UPDATE tdac.users
        SET hashed_password = $2,
            token_gen = $3
        WHERE id = $1
        """,
        current_user["id"],
        hashed_password,
        new_token_gen,
    )

    access_token = create_access_token(
        {
            "sub": str(current_user["id"]),
            "token_gen": new_token_gen,
        }
    )

    refresh_token = create_refresh_token(
        {
            "sub": str(current_user["id"]),
            "token_gen": new_token_gen,
        }
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }

# Logout
@router.post('/logout')
async def logout(user=Depends(get_current_user)):
    await database.pool.execute(
        """
        UPDATE tdac.users
        SET token_gen = token_gen + 1
        WHERE id = $1
        """,
        user["id"]
    )

    return {
        "message":"Logged out successfully"
    }

# Create User
@router.post("/users")
async def create_new_user(
    user_data: UserCreate,
    current_admin: dict = Depends(get_current_admin),
):
    if user_data.role_id not in(2,10):
        raise HTTPException(
            status_code=400,
            detail="Only engineer or client accounts can be created"
        )

    existing_user = await get_user_by_username(user_data.username)

    if existing_user is not None:
        raise HTTPException(
            status_code=409,
            detail="Username already exists"
        )

    hashed_password = hash_password(user_data.password)

    user = await create_user(
        username=user_data.username,
        hashed_password=hashed_password,
        role_id=user_data.role_id
    )

    if user is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid role"
        )

    return{
        "message":"User created successfully",
        "user":{
            "id":user["id"],
            "username":user["username"],
            "role_id":user["role_id"]
        }
    }

# Get all users
@router.get("/users")
async def get_users(
    current_admin: dict = Depends(get_current_admin)
    ):
    users = await get_all_users()

    return {
        "users": [
            {
                "id": user["id"],
                "username": user["username"],
                "role_id": user["role_id"],
                "role_name": user["role_name"],
                "is_active": user["is_active"],
                "created_at": user["created_at"],
            }
            for user in users
        ]
    }

# Get single user
@router.get("/users/{user_id}")
async def get_single_user(
    user_id: int,
    current_admin: dict = Depends(get_current_admin)
):
    user = await get_user_by_id(user_id)

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    return {
        "id": user["id"],
        "username": user["username"],
        "role_id": user["role_id"],
        "role_name": user["role_name"],
        "is_active": user["is_active"],
        "created_at": user["created_at"]
    }

# Update User
@router.put("/users/{user_id}")
async def update_existing_user(
    user_id: int,
    user_data: UserUpdate,
    current_admin: dict = Depends(get_current_admin)
):
    existing_user = await get_user_by_id(user_id)

    if existing_user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    # make sure at least one field is being changed
    if (
        user_data.username is None
        and user_data.password is None
        and user_data.role_id is None
    ):
        raise HTTPException(
            status_code=400,
            detail="No changes provided"
        )

    # Check username uniqueness if username is being changed
    if user_data.username is not None:
        username_user = await get_user_by_username(
            user_data.username
        )

        if (
            username_user is not None
            and username_user["id"] != user_id
        ):
            raise HTTPException(
                status_code=409,
                detail="Username already exists"
            )

    # Hash password only if a new password was provided
    hashed_password = None

    if user_data.password is not None:
        hashed_password = hash_password(
            user_data.password
        )

    # Only engineer/client roles are allowed
    if(
        user_data.role_id is not None and user_data.role_id not in (2,10)
    ):
        raise HTTPException(
            status_code=400,
            detail="Only engineer or client roles are allowed",
        )

    user = await update_user(
        user_id=user_id,
        username=user_data.username,
        hashed_password=hashed_password,
        role_id=user_data.role_id
    )
    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )
    return {
        "message": "User updated successfully",
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role_id": user["role_id"],
            "is_active": user["is_active"],
            "created_at": user["created_at"],
        }
    }

# Change user status
@router.patch("/users/{user_id}/status")
async def change_user_status(
    user_id: int,
    is_active: bool,
    current_admin: dict = Depends(get_current_admin)
):
    existing_user = await get_user_by_id(user_id)

    if existing_user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    # Prevent admin from accidentally disabling themselves
    if existing_user["id"] == current_admin["id"]:
        raise HTTPException(
            status_code=400,
            detail="You cannot change your own account status"
        )

    user = await update_user_status(
        user_id=user_id,
        is_active=is_active
    )

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    return {
        "message": (
            "User activated successfully"
            if is_active
            else "User deactivated successfully"
        ),
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role_id": user["role_id"],
            "is_active": user["is_active"],
        }
    }

# Delete user
@router.delete("/users/{user_id}")
async def delete_existing_user(
    user_id: int,
    current_admin: dict = Depends(get_current_admin)
):
    existing_user = await get_user_by_id(user_id)

    if existing_user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    # Prevent admin from deleting themselves
    if existing_user["id"] == current_admin["id"]:
        raise HTTPException(
            status_code=400,
            detail="You cannot delete your own account"
        )

    user = await delete_user(user_id)

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    return {
        "message": "User deleted successfully",
        "user": {
            "id": user["id"],
            "username": user["username"],
        }
    }  

