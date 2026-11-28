"""Pruebas de consistencia del catálogo de roles y permisos."""
from vexa.permissions import catalog


def test_every_role_permission_is_documented():
    for role, permisos in catalog.ROLE_PERMISSIONS.items():
        assert permisos <= set(catalog.PERMISSIONS), role
    assert set(catalog.ROLE_PERMISSIONS) == set(catalog.ROLES)


def test_roles_are_nested():
    lawyer = catalog.ROLE_PERMISSIONS["lawyer"]
    chief = catalog.ROLE_PERMISSIONS["chief_lawyer"]
    admin = catalog.ROLE_PERMISSIONS["admin"]
    assert lawyer <= chief <= admin
