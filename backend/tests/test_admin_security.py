from app.core.security import AuthContext, require_admin


def test_require_admin_denies_user_role():
    ctx = AuthContext(user_id="u", tenant_id="t", email="e", role="user")
    try:
      require_admin(ctx)
      assert False, "Expected exception"
    except Exception as exc:
      assert "Admin role required" in str(exc)


def test_require_admin_accepts_admin_role():
    ctx = AuthContext(user_id="u", tenant_id="t", email="e", role="admin")
    out = require_admin(ctx)
    assert out.role == "admin"
