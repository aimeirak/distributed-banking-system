from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST


def login_page(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        user = authenticate(
            request,
            username=username,
            password=password
        )

        if user is not None:
            try:
                profile = user.profile
            except Exception:
                profile = None

            if profile is None:
                messages.error(
                    request,
                    "Your user profile has not been configured."
                )
                return render(request, "auth/login.html")

            if profile.role != "CUSTOMER":
                messages.error(
                    request,
                    "You do not have permission to access the customer portal."
                )
                return render(request, "auth/login.html")

            login(request, user)

            next_url = request.GET.get("next") or request.POST.get("next")

            if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)

            return redirect("dashboard")

        messages.error(
            request,
            "Invalid username or password."
        )

    return render(request, "auth/login.html")


@login_required(login_url="login")
@require_POST
def logout_page(request):
    logout(request)
    messages.success(request, "You have successfully logged out.")
    return redirect("login")