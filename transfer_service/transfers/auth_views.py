from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST


# These are the roles currently supported by UserProfile.
# Keep this list aligned with UserProfile.Role in transfers/models.py.
SUPPORTED_LOGIN_ROLES = {
    "CUSTOMER",
    "BANK_OFFICER",
    "BANK_ADMIN",
    "SYSTEM_ADMIN",
}


def _get_user_profile(user):
    """Return the user's profile, or None when it is not configured."""
    try:
        return user.profile
    except (AttributeError, user._meta.model.DoesNotExist):
        return None
    except Exception:
        # Handles a missing reverse OneToOne profile (RelatedObjectDoesNotExist).
        return None


def _get_post_login_url(request, user, profile):
    """
    Resolve a safe post-login destination.

    At present, the project has one shared dashboard route named 'dashboard'.
    Role-specific dashboard routes can be added later without changing login.
    """
    next_url = request.POST.get("next") or request.GET.get("next")

    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url

    # All roles currently use the existing dashboard. Its pages and APIs must
    # continue enforcing their own role permissions.
    return "dashboard"


def login_page(request):
    if request.user.is_authenticated:
        profile = _get_user_profile(request.user)
        if profile and profile.role in SUPPORTED_LOGIN_ROLES:
            return redirect(_get_post_login_url(request, request.user, profile))

        messages.error(request, "Your account does not have an authorized application role.")
        logout(request)

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        user = authenticate(
            request,
            username=username,
            password=password,
        )

        if user is None:
            messages.error(request, "Invalid username or password.")
            return render(request, "auth/login.html")

        profile = _get_user_profile(user)

        if profile is None:
            messages.error(
                request,
                "Your user profile has not been configured. Please contact the system administrator.",
            )
            return render(request, "auth/login.html")

        if profile.role not in SUPPORTED_LOGIN_ROLES:
            messages.error(
                request,
                "Your account role is not authorized to access this application.",
            )
            return render(request, "auth/login.html")

        # Establish the Django session only after credentials and role are valid.
        login(request, user)

        return redirect(_get_post_login_url(request, user, profile))

    return render(request, "auth/login.html")


@login_required(login_url="login")
@require_POST
def logout_page(request):
    logout(request)
    messages.success(request, "You have successfully logged out.")
    return redirect("login")
