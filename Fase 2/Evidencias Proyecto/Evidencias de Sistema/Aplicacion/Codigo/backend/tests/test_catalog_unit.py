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


def test_only_admin_changes_deadlines_and_lawyers_do_not_manage():
    assert [r for r, p in catalog.ROLE_PERMISSIONS.items() if "cases.set_deadline" in p] == ["admin"]
    assert not catalog.ROLE_PERMISSIONS["lawyer"] & catalog.MANAGEMENT_PERMISSIONS
    assert catalog.MANAGEMENT_PERMISSIONS <= set(catalog.PERMISSIONS)


def test_chief_lawyer_can_only_assign_lawyers():
    assert catalog.ROLES_ASSIGNABLE_BY["chief_lawyer"] == {"lawyer"}
    assert catalog.ROLES_ASSIGNABLE_BY["admin"] == set(catalog.ROLES)
    assert "lawyer" not in catalog.ROLES_ASSIGNABLE_BY
