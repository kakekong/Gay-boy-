from app.core.permissions import Role, at_least


def test_hierarchy():
    assert at_least(Role.SALES, Role.DIRECTOR)
    assert at_least(Role.MANAGER, Role.DIRECTOR)
    assert at_least(Role.SALES, Role.SALES)
    assert not at_least(Role.MANAGER, Role.SALES)
    assert not at_least(Role.DIRECTOR, Role.MANAGER)
