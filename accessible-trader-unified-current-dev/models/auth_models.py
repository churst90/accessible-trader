# models/auth_models.py

from sqlalchemy import Column, Integer, String, Text, Boolean, TIMESTAMP, ForeignKey, DECIMAL, JSON, Date, Enum
from sqlalchemy.sql import func
from app_extensions.auth_db_setup import AuthUserBase # Import the Base from your setup file

class User(AuthUserBase):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(255), nullable=False, unique=True)
    password = Column(String(255), nullable=False) # password_hash would be a better name
    last_login = Column(TIMESTAMP)
    email = Column(String(255), nullable=False, unique=True)
    # The ENUM type needs careful handling with SQLAlchemy dialects for MySQL/MariaDB
    # You might prefer a String column and application-level validation/mapping
    role = Column(Enum('admin', 'editor', 'user', name='user_roles_enum'), nullable=False, default='user')
    nickname = Column(String(50))
    location = Column(String(255))
    bio = Column(Text)
    profile_picture = Column(String(255))
    registration_date = Column(TIMESTAMP, server_default=func.now())
    birthdate = Column(Date)

class Role(AuthUserBase):
    __tablename__ = 'roles'
    RoleID = Column(Integer, primary_key=True, autoincrement=True)
    RoleName = Column(String(255), nullable=False, unique=True)

class Permission(AuthUserBase):
    __tablename__ = 'permissions'
    PermissionID = Column(Integer, primary_key=True, autoincrement=True)
    PermissionName = Column(String(255), nullable=False, unique=True)

class RolePermission(AuthUserBase):
    __tablename__ = 'role_permissions'
    RoleID = Column(Integer, ForeignKey('roles.RoleID'), primary_key=True)
    PermissionID = Column(Integer, ForeignKey('permissions.PermissionID'), primary_key=True)

class PasswordReset(AuthUserBase):
    __tablename__ = 'password_resets'
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False) # Assuming FK to users.id
    token = Column(String(255), nullable=False, index=True)
    expires_at = Column(TIMESTAMP, nullable=False)
    created_at = Column(TIMESTAMP, nullable=False, server_default=func.now())