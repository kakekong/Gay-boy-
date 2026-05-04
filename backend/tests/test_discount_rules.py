from app.core.approval import evaluate_discount
from app.core.permissions import Role


def test_under_5_auto():
    assert evaluate_discount(0).required_role is None
    assert evaluate_discount(5).required_role is None


def test_5_to_15_manager():
    assert evaluate_discount(7).required_role == Role.MANAGER
    assert evaluate_discount(15).required_role == Role.MANAGER


def test_above_15_director():
    assert evaluate_discount(15.01).required_role == Role.DIRECTOR
    assert evaluate_discount(40).required_role == Role.DIRECTOR
