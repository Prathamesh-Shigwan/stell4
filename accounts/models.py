# accounts/models.py
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.db.models.signals import post_save
from django.dispatch import receiver
from django_otp.models import Device
from django.core.mail import send_mail
from django.conf import settings
import random


class User(AbstractUser):
    ROLE_CHOICES = (
        ('user', 'User'),
        ('staff', 'Staff'),
        ('content_manager', 'Content Manager'),
        ('inventory_manager', 'Inventory Manager'),
        ('finance_manager', 'Finance Manager'),
        ('admin', 'Admin'),
    )

    email = models.EmailField(unique=True, max_length=100)
    username = models.CharField(max_length=100, unique=True)
    bio = models.TextField(blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='user')

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ['username']

    def __str__(self):
        return self.username

    def save(self, *args, **kwargs):
        if self.role in ['admin', 'content_manager', 'inventory_manager', 'finance_manager', 'staff']:
            self.is_staff = True
        else:
            self.is_staff = False
        super().save(*args, **kwargs)

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    phone = models.CharField(max_length=200, unique=True, blank=True, null=True)
    address = models.CharField(max_length=200, blank=True, null=True)
    city = models.CharField(max_length=200, blank=True, null=True)
    state = models.CharField(max_length=200, blank=True, null=True)
    zipcode = models.CharField(max_length=200, blank=True, null=True)
    country = models.CharField(max_length=200, blank=True, null=True)
    date_modified = models.DateField(auto_now=True)

    def __str__(self):
        return self.user.username






class CustomEmailOTPDevice(Device):
    otp_token = models.CharField(max_length=6, blank=True, null=True)

    def generate_challenge(self):
        self.otp_token = str(random.randint(100000, 999999))
        self.save()

        subject = "Welcome to Stellars – Your OTP Verification Code"
        message = f"""
Hello {self.user.username},

Thanks for signing up with Stellars – your go-to destination for premium bags and accessories! 🎒👜

To complete your registration, please verify your email address.

🔐 Your OTP code is: {self.otp_token}

This OTP is valid for the next 10 minutes. Enter it on the website to activate your account and start shopping.

If you didn’t request this, you can safely ignore this email.

Cheers,  
Team Stellars  
www.stellarsonline.com
"""
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [self.user.email])
        return True

    def verify_token(self, token):
        return token == self.otp_token


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)


@receiver(post_save, sender=User)
def set_superuser_role(sender, instance, created, **kwargs):
    if created and instance.is_superuser and instance.role != 'admin':
        instance.role = 'admin'
        instance.save()

