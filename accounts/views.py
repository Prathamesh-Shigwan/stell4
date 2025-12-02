import random
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import render, get_object_or_404, redirect
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.decorators import user_passes_test
from django.urls import reverse

from .forms import UserRegisterForm, UserUpdateForm, UserInfoForm, OTPVerificationForm, UserRoleUpdateForm, ProfileForm
from .models import User, Profile, CustomEmailOTPDevice  # Include your custom OTP device here
from products.forms import ShippingForm, BillingForm
from products.models import ShippingAddress, BillingAddress
from .forms import PasswordResetRequestForm
from django.contrib.auth.forms import SetPasswordForm
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.contrib.auth.tokens import default_token_generator
from django.template.loader import render_to_string



def sign_up(request):
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            new_user = form.save(commit=False)
            new_user.is_active = False
            new_user.save()

            device, created = CustomEmailOTPDevice.objects.get_or_create(user=new_user, name='custom_email_otp')
            device.generate_challenge()

            request.session['user_id'] = new_user.id
            request.session['signup_flow'] = True  # Set flag for redirect control
            messages.success(request, 'An OTP has been sent to your email. Please verify to complete the registration.')
            return redirect('accounts:verify_signup_otp')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
    else:
        form = UserRegisterForm()

    return render(request, 'signup.html', {'form': form})


def verify_signup_otp(request):
    user_id = request.session.get('user_id')
    if not user_id:
        messages.error(request, "Session expired, please sign up again.")
        return redirect('accounts:sign_up')

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        messages.error(request, "User does not exist. Please sign up again.")
        return redirect('accounts:sign_up')

    if request.method == 'POST':
        form = OTPVerificationForm(request.POST)
        if form.is_valid():
            otp = form.cleaned_data['otp']
            try:
                device = CustomEmailOTPDevice.objects.get(user=user, name='custom_email_otp')
                if device.verify_token(otp):
                    user.is_active = True
                    user.save()
                    login(request, user)
                    messages.success(request, "Your account has been verified and you are now logged in.")
                    request.session.pop('signup_flow', None)  # Remove flag after use
                    return redirect("accounts:user_profile")
                else:
                    form.add_error('otp', 'Invalid OTP')
            except CustomEmailOTPDevice.DoesNotExist:
                messages.error(request, "OTP device not found. Please contact support.")
    else:
        form = OTPVerificationForm()

    return render(request, 'verify_signup_otp.html', {'form': form})


def login_view(request):
    """if request.user.is_authenticated:
        messages.warning(request, f"You are already logged in as {request.user}.")
        return redirect('products:home')"""

    if request.method == 'POST':
        if request.user.is_authenticated:
            messages.warning(request, f"You are already logged in as {request.user}.")
            return redirect('products:home')
        email = request.POST.get('email')
        password = request.POST.get('password')
        user = authenticate(email=email, password=password)

        if user:
            if not user.is_active:
                messages.error(request, "Your account is not verified. Please verify your email.")
                return redirect('accounts:login')

            device, created = CustomEmailOTPDevice.objects.get_or_create(user=user, name='custom_email_otp')
            device.generate_challenge()

            request.session['email'] = email
            request.session['password'] = password
            request.session['signup_flow'] = False  # This is a login flow
            return redirect('accounts:verify_otp')
        else:
            messages.error(request, "Invalid email or password")

    context = {'form': UserRegisterForm()}
    return render(request, 'login.html', context)


def verify_otp(request):
    email = request.session.get('email')
    password = request.session.get('password')

    if not email or not password:
        messages.error(request, "Session expired, please login again.")
        return redirect('accounts:login')

    user = authenticate(email=email, password=password)
    if not user:
        messages.error(request, "Invalid credentials. Please login again.")
        return redirect('accounts:login')

    if request.method == 'POST':
        form = OTPVerificationForm(request.POST)
        if form.is_valid():
            otp = form.cleaned_data['otp']
            try:
                device = CustomEmailOTPDevice.objects.get(user=user, name='custom_email_otp')
                if device.verify_token(otp):
                    login(request, user)
                    messages.success(request, "Logged in successfully")

                    # Decide redirect based on signup/login flag
                    if request.session.pop('signup_flow', False):
                        return redirect("accounts:user_profile")
                    else:
                        return redirect("products:home")

                else:
                    form.add_error('otp', 'Invalid OTP')
            except CustomEmailOTPDevice.DoesNotExist:
                messages.error(request, "OTP device not found. Please contact support.")
    else:
        form = OTPVerificationForm()

    return render(request, 'verify_otp.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.success(request, "You have been logged out.")
    return redirect('accounts:login')


def user_profile(request):
    if request.user.is_authenticated:
        current_user = User.objects.get(id=request.user.id)
        profile, _ = Profile.objects.get_or_create(user=current_user)  # Ensure profile exists

        user_form = UserUpdateForm(request.POST or None, instance=current_user)
        profile_form = ProfileForm(request.POST or None, instance=profile)

        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            profile_form.save()
            messages.success(request, "Your profile has been updated!")
            return redirect('home')

        return render(request, 'user-profile.html', {
            'user_form': user_form,
            'profile_form': profile_form,
        })
    else:
        messages.error(request, "You need to be logged in to update your profile.")
        return redirect('home')


def update_info(request):
    if not request.user.is_authenticated:
        messages.error(request, "You must be logged in to update your profile.")
        return redirect('accounts:login')

    profile, _ = Profile.objects.get_or_create(user=request.user)

    billing_address = BillingAddress.objects.filter(user=request.user).first()
    shipping_address = ShippingAddress.objects.filter(user=request.user).first()

    if request.method == 'POST':
        billing_form = BillingForm(request.POST, instance=billing_address)
        shipping_form = ShippingForm(request.POST, instance=shipping_address)
        if billing_form.is_valid() and shipping_form.is_valid():
            saved_billing = billing_form.save(commit=False)
            saved_billing.user = request.user
            saved_billing.save()

            saved_shipping = shipping_form.save(commit=False)
            saved_shipping.user = request.user
            saved_shipping.save()

            messages.success(request, "Your billing and shipping information has been updated.")
            return redirect('products:checkout')
    else:
        billing_form = BillingForm(instance=billing_address)
        shipping_form = ShippingForm(instance=shipping_address)

    context = {
        'billing_form': billing_form,
        'shipping_form': shipping_form
    }
    return render(request, 'update_info.html', context)


def password_reset_request(request):
    if request.method == "POST":
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"]
            user = User.objects.filter(email=email).first()
            if user:
                token = default_token_generator.make_token(user)
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                reset_link = request.build_absolute_uri(
                    reverse("password_reset_confirm", kwargs={"uidb64": uid, "token": token})
                )

                subject = "Stellars – Reset your password"
                message = f"""
Hi {user.username},

We received a request to reset your Stellars account password.

Click the link below to reset your password:
🔗 {reset_link}

If you didn’t request this, you can safely ignore this email.

– Team Stellars
"""
                send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [user.email])
                messages.success(request, "A password reset link has been sent to your email.")
                return redirect("accounts:login")
            else:
                messages.error(request, "No account found with that email.")
    else:
        form = PasswordResetRequestForm()
    return render(request, "password_reset_request.html", {"form": form})


def password_reset_confirm(request, uidb64, token):
    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        user = None

    if user is not None and default_token_generator.check_token(user, token):
        if request.method == "POST":
            form = SetPasswordForm(user, request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, "Your password has been reset. You can now log in.")
                return redirect("accounts:login")
        else:
            form = SetPasswordForm(user)
        return render(request, "password_reset_confirm.html", {"form": form})
    else:
        messages.error(request, "The reset link is invalid or has expired.")
        return redirect("accounts:password_reset_request")


def is_admin(user):
    return user.is_authenticated and user.role == 'admin'


@user_passes_test(is_admin)
def manage_users(request):
    users = User.objects.exclude(is_superuser=True)
    return render(request, 'custom_admin/manage_users.html', {'users': users})


@user_passes_test(is_admin)
def update_user_role(request, user_id):
    user = get_object_or_404(User, id=user_id)
    if request.method == 'POST':
        form = UserRoleUpdateForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            return redirect('custom_admin:manage_users')
    else:
        form = UserRoleUpdateForm(instance=user)
    return render(request, 'custom_admin/update_user_role.html', {'form': form, 'user': user})











