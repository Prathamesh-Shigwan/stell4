# products/views.py
import io
import base64
import qrcode
from PIL import Image

import hmac
import hashlib
import json

from django.core.exceptions import PermissionDenied
from django.db.models import Q, Min, OuterRef, Exists, Avg

import logging
from django.utils import timezone
from datetime import timedelta
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from .models import Order
from datetime import timedelta
from decimal import Decimal
from django.contrib.admin.views.decorators import staff_member_required
from venv import logger
from django.utils import timezone
from datetime import datetime, timedelta
from django.core.mail import send_mail
from django.db import transaction
from django.http import JsonResponse, HttpResponse, HttpResponseRedirect
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_http_methods, require_POST
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.conf import settings
import razorpay
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags
from .models import *
from .forms import *
from django.shortcuts import render
from django.contrib.auth.models import User
from .models import Order, Product, Cart, Brand
from django.db.models import Sum, Count
from blog.models import Blog  # Import Blog model
from django.contrib.admin import AdminSite
from django.db.models.functions import TruncDay, TruncMonth
from django.utils.timezone import now
from decimal import Decimal
from django.urls import reverse_lazy

client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
COLOR_HEX_MAP = {
    "grey": "#808080",
    "lemon": "#FFF700",
    "white": "#FFFFFF",
    "red": "#FF0000",
    "black": "#000000",
    "pink": "#FFC0CB",
    "navy": "#000080",
    "brown": "#A52A2A",
    "beige": "#F5F5DC",
    "tan": "#D2B48C",
    "burgundy": "#800020",
    "olive": "#808000",
    "camel": "#C19A6B",
    "cream": "#FFFDD0",
    "teal": "#008080",
    "purple": "#800080",
    "orange": "#FFA500",
    "gold": "#FFD700",
    "silver": "#C0C0C0",
    "blue": "#0000FF",
    "green": "#008000",
    "yellow": "#FFFF00",
    "coral": "#FF7F50",
    "turquoise": "#40E0D0",
    "khaki": "#F0E68C",
    "lavender": "#E6E6FA",
    "mint": "#98FF98",
    "taupe": "#483C32",
    "blush": "#F4C2C2",
    "cognac": "#9A463D"
}

def home(request):
    products = Product.objects.filter(product_status="published", featured=True).order_by('-id')

    # Add first variant, size, and discount to each product
    for product in products:
        first_variant = product.variants.first()  # Related name 'variants'
        if first_variant:
            product.first_variant = first_variant
            first_size = first_variant.size_options.first()
            if first_size:
                product.first_size = first_size
                if first_size.old_price and first_size.old_price > first_size.price:
                    discount = round(((first_size.old_price - first_size.price) / first_size.old_price) * 100)
                    product.first_discount = discount
                else:
                    product.first_discount = None
            else:
                product.first_size = None
                product.first_discount = None
        else:
            product.first_variant = None
            product.first_size = None
            product.first_discount = None

    sub_categories = SubCategory.objects.all().order_by('-id')[:9]
    color_choices = ProductVariant.objects.values_list('color', flat=True).distinct()
    banner_images = BannerImage.objects.filter(is_active=True)
    blogs = Blog.objects.order_by('-created_at')[:2]
    featured_products = Product.objects.filter(featured=True).order_by('-id')[:8]
    main_categories = MainCategory.objects.prefetch_related('subcategories').all()
    site_content = SiteContent.objects.first() # Fetch the site content
    brands = Brand.objects.filter(is_active=True)

    context = {
        'products': products,
        'sub_categories': sub_categories,
        'color_choices': color_choices,
        'banner_images': banner_images,
        'blogs': blogs,
        'featured_products': featured_products,
        'main_categories': main_categories,
        'site_content': site_content,
        'brands': brands,
    }

    return render(request, 'home.html', context)


@require_POST
@login_required
@csrf_protect
def apply_coupon(request):
    code = request.POST.get('code')
    try:
        cart = Cart.objects.get(user=request.user)
    except Cart.DoesNotExist:
        return JsonResponse({"success": False, "message": "Cart not found."})

    try:
        discount = DiscountCode.objects.get(code=code)

        # Temporarily assign to cart to check validity with current cart state
        # (The is_valid method on DiscountCode needs a cart object)
        cart.discount_code = discount  # Set it for validation
        if not discount.is_valid(user=request.user, cart=cart):
            cart.discount_code = None  # If not valid, clear it
            cart.save()  # Save to clear any previously set invalid coupon
            return JsonResponse({"success": False, "message": "Coupon is not valid."})

        # At this point, the coupon is valid. Assign and save the cart.
        # The cart.save() will now handle updating cart.total to the discounted amount
        # and marking the coupon as used (if you keep that logic in Cart.save).

        # Before saving, get the discount amount that will be applied for the response
        # We need the subtotal here to calculate the discount for the response
        cart.subtotal = cart.calculate_subtotal()  # Ensure subtotal is fresh for calculation
        calculated_discount_amount = cart.get_discount_amount()

        cart.discount_code = discount  # Re-assign if it was cleared for validation
        cart.save()  # This save updates cart.total to discounted value

        # Safely get shipping charge
        site_settings = SiteSettings.objects.first()
        shipping = site_settings.shipping_charge if site_settings else Decimal('0.00')

        final_total = cart.total + shipping  # cart.total is already discounted

        return JsonResponse({
            "success": True,
            "message": "Coupon applied successfully!",
            "discount": float(calculated_discount_amount),
            "final_total": float(final_total),
            "cart_total_after_discount": float(cart.total)  # Show the cart's new total
        })

    except DiscountCode.DoesNotExist:
        return JsonResponse({"success": False, "message": "Invalid coupon code."})


@require_POST
@login_required
@csrf_protect
def remove_coupon(request):
    try:
        cart = Cart.objects.get(user=request.user)
        # To accurately reverse the usage tracking, you might need to handle it here
        # or have a more sophisticated usage tracking system.
        # For simplicity, we'll just remove the discount code.
        # Note: If used_by is marked in Cart.save(), removing it here won't "un-mark" it.
        cart.discount_code = None
        cart.save()  # This save will recalculate total based on subtotal

        # Safely get shipping charge
        site_settings = SiteSettings.objects.first()
        shipping = site_settings.shipping_charge if site_settings else Decimal('0.00')


        final_total = cart.total + shipping  # cart.total is now the subtotal

        return JsonResponse({
            "success": True,
            "message": "Coupon removed successfully.",
            "final_total": float(final_total),
            "cart_total_after_remove": float(cart.total)
        })
    except Cart.DoesNotExist:
        return JsonResponse({"success": False, "message": "Cart not found."})


@login_required(login_url=reverse_lazy('accounts:login'))
@csrf_protect
def cart_view(request):
    cart, _ = Cart.objects.get_or_create(user=request.user)

    # Ensure cart totals are up-to-date before rendering
    # cart.save() # This will ensure subtotal and total are calculated correctly

    items = CartItem.objects.filter(cart=cart)  # Assuming CartItem model exists

    # Get the discount amount for display
    discount_amount_for_display = cart.get_discount_amount() if cart.discount_code else Decimal('0.00')

    site_settings = SiteSettings.objects.first()
    shipping = site_settings.shipping_charge if site_settings else Decimal('0.00')

    # cart.total is already the discounted total
    final_total = cart.total + shipping

    context = {
        'cart': cart,
        'items': items,
        'subtotal': cart.subtotal,  # Display the pre-discount total
        'total': cart.total,  # Display the post-discount total (which is cart.total)
        'discount': discount_amount_for_display,
        'final_total': final_total,
        'shipping': shipping,
    }
    return render(request, 'cart.html', context)

def contact(request):
    success_message = None  # Initialize the success message variable
    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data['name']
            email = form.cleaned_data['email']  # Sender's email
            subject = form.cleaned_data['subject']
            message = form.cleaned_data['message']

            email_subject = f"Contact Form Submission from {name}: {subject}"
            email_message = f"Message from {email}:\n\n{message}"

            try:
                send_mail(
                    email_subject,
                    email_message,
                    email,  # From email (sender's email)
                    ['prathameshshigwan222@gmail.com'],  # To email
                    fail_silently=False,
                )
                success_message = "Your message has been sent successfully. Thank you for contacting us!"
                form = ContactForm()  # <-- ADD THIS LINE to create a new, empty form
            except Exception as e:
                success_message = "An error occurred while sending your message. Please try again."
    else:
        form = ContactForm()

    return render(request, 'contact.html', {
        'form': form,
        'success_message': success_message
    })

def base(request, cid=None, is_subcategory=False):
    color = request.GET.get('color')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    page = request.GET.get('page', 1)
    products = Product.objects.filter(product_status="published", featured=True).order_by('-id')

    if cid:
        if is_subcategory:
            category = get_object_or_404(SubCategory, sid=cid)
            products = products.filter(sub_category=category)
        else:
            category = get_object_or_404(MainCategory, cid=cid)
            products = products.filter(main_category=category)

    if min_price and max_price:
        products = products.filter(price__gte=min_price, price__lte=max_price)

    if color:
        products = products.filter(variants__color=color).distinct()

    main_categories = MainCategory.objects.all().order_by('-id')
    sub_categories = SubCategory.objects.all().order_by('-id')

    paginator = Paginator(products, 10)
    try:
        products_page = paginator.page(page)
    except PageNotAnInteger:
        products_page = paginator.page(1)
    except EmptyPage:
        products_page = paginator.page(paginator.num_pages)

    color_choices = {color[0]: color[1] for color in ProductVariant.COLOR_CHOICES}
    site_content = SiteContent.objects.first() # Fetch the site content

    context = {
        'products': products_page,
        'main_categories': main_categories,
        'sub_categories': sub_categories,
        'color_choices': color_choices,
        'color_hex_map': COLOR_HEX_MAP,
        'site_content': site_content,
    }
    return render(request, 'base11.html', context)


def product_grid(request, cid=None, is_subcategory=False):
    color = request.GET.get('color')
    min_price = request.GET.get('min_price')
    max_price = request.GET.get('max_price')
    gender = request.GET.get('gender')
    page = request.GET.get('page', 1)
    sort = request.GET.get('sort')

    # Filter only products that have at least one valid variant with a size option
    valid_variants = ProductVariant.objects.filter(
        product=OuterRef('pk'),
        size_options__isnull=False
    )

    products = Product.objects.filter(
        product_status="published"
    ).annotate(
        has_valid_variant=Exists(valid_variants)
    ).filter(
        has_valid_variant=True
    ).prefetch_related(
        'variants__size_options'
    ).distinct()

    # Category filtering
    if cid:
        if is_subcategory:
            category = get_object_or_404(SubCategory, sid=cid)
            products = products.filter(sub_category=category)
        else:
            category = get_object_or_404(MainCategory, cid=cid)
            products = products.filter(main_category=category)

    # Gender filter
    if gender:
        gender_list = gender.split(',')
        products = products.filter(variants__gender__in=gender_list).distinct()

    # Price filter
    if min_price and max_price:
        products = products.filter(
            variants__size_options__price__gte=min_price,
            variants__size_options__price__lte=max_price
        ).distinct()

    # Color filter
    if color:
        products = products.filter(variants__color=color).distinct()

    # Sorting
    if sort == 'low_to_high':
        products = products.annotate(min_price=Min('variants__size_options__price')).order_by('min_price')
    elif sort == 'high_to_low':
        products = products.annotate(min_price=Min('variants__size_options__price')).order_by('-min_price')

    # Pagination
    paginator = Paginator(products, 9)
    try:
        products_page = paginator.page(page)
    except PageNotAnInteger:
        products_page = paginator.page(1)
    except EmptyPage:
        products_page = paginator.page(paginator.num_pages)

    # Context
    main_categories = MainCategory.objects.all().order_by('-id')
    sub_categories = SubCategory.objects.all().order_by('-id')
    color_choices = {color[0]: color[1] for color in Product.COLOR_CHOICES}

    context = {
        'products': products_page,
        'main_categories': main_categories,
        'sub_categories': sub_categories,
        'color_choices': color_choices.items(),
        'color_hex_map': COLOR_HEX_MAP,
        'sort': sort,
    }

    return render(request, 'product-grid.html', context)


def product_list(request):
    page = request.GET.get('page', 1)
    products = Product.objects.filter(product_status="published", featured=True).order_by('-id')

    paginator = Paginator(products, 9)
    try:
        products_page = paginator.page(page)
    except PageNotAnInteger:
        products_page = paginator.page(1)
    except EmptyPage:
        products_page = paginator.page(paginator.num_pages)

    context = {
        'products': products_page,
    }
    return render(request, 'product-list.html', context)



def product_details(request, pid):
    product = get_object_or_404(Product, pid=pid)
    variants = product.variants.prefetch_related('extra_images', 'size_options')
    default_variant = variants.first()

    reviews_list = product.reviews.filter(user__isnull=False).order_by('-date')
    average_rating = reviews_list.aggregate(Avg('rating')).get('rating__avg') or 0

    user_review = None
    other_reviews = reviews_list

    # --- NEW: Check if the user can add a review ---
    can_add_review = False
    if request.user.is_authenticated:
        user_review = reviews_list.filter(user=request.user).first()
        if user_review:
            other_reviews = reviews_list.exclude(id=user_review.id)

        # Check if the user has a delivered order for this product
        if Order.objects.filter(
                user=request.user,
                status='delivered',
                items__product=product
        ).exists():
            can_add_review = True
    # --- END OF NEW LOGIC ---

    paginator = Paginator(other_reviews, 5)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    is_editing = False
    review_to_edit = None
    edit_review_id = request.GET.get('edit')
    if edit_review_id and request.user.is_authenticated:
        try:
            review_to_edit = ProductsReviews.objects.get(id=edit_review_id, user=request.user)
            if can_add_review:  # Can only edit if they have permission to review in the first place
                is_editing = True
        except ProductsReviews.DoesNotExist:
            messages.error(request, "Review not found or you don't have permission to edit it.")

    review_form = ReviewForm(instance=review_to_edit) if is_editing else ReviewForm()

    context = {
        'product': product,
        'variants': variants,
        'variant': default_variant,
        'page_obj': page_obj,
        'average_rating': average_rating,
        'review_count': reviews_list.count(),
        'review_form': review_form,
        'user_review': user_review,
        'is_editing': is_editing,
        'review_to_edit': review_to_edit,
        'can_add_review': can_add_review,  # <-- Pass the permission to the template
    }
    return render(request, 'product-details.html', context)


# This view for adding a review remains the same
@login_required
def add_review(request, pid):
    product = get_object_or_404(Product, pid=pid)
    if request.method == 'POST':
        if ProductsReviews.objects.filter(user=request.user, product=product).exists():
            messages.error(request, 'You have already submitted a review for this product.')
            return redirect('products:product_details', pid=pid)

        form = ReviewForm(request.POST)
        if form.is_valid():
            new_review = form.save(commit=False)
            new_review.user = request.user
            new_review.product = product
            if Order.objects.filter(user=request.user, items__product=product, status='completed').exists():
                new_review.verified_purchase = True
            new_review.save()
            messages.success(request, 'Your review has been submitted successfully!')
            return redirect('products:product_details', pid=pid)
    return redirect('products:product_details', pid=pid)


# This view for editing (handling the POST) also remains
@login_required
def edit_review(request, review_id):
    review = get_object_or_404(ProductsReviews, id=review_id)
    if review.user != request.user:
        raise PermissionDenied

    if request.method == 'POST':
        form = ReviewForm(request.POST, instance=review)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your review has been updated successfully!')
            return redirect('products:product_details', pid=review.product.pid)
    else:
        # If not POST, just redirect to the product page with the edit flag
        return redirect(f"{reverse('products:product_details', args=[review.product.pid])}?edit={review.id}")

def get_variant_data(request, variant_id):
    try:
        variant = ProductVariant.objects.get(id=variant_id)
        sizes = VariantSizeOption.objects.filter(variant=variant)
        extra_images = [img.image.url for img in variant.extra_images.all()]

        return JsonResponse({
            "name": f"{variant.product.name} - {variant.color}",
            "price": str(sizes[0].price) if sizes else "0.00",
            "old_price": str(sizes[0].old_price) if sizes and sizes[0].old_price else "",
            "image": variant.image.url if variant.image else "",
            "video": variant.video.url if variant.video else "",
            "sizes": [
                {
                    "size": s.size,
                    "stock_quantity": s.stock_quantity,
                    "price": str(s.price),
                    "old_price": str(s.old_price) if s.old_price else ""
                } for s in sizes
            ],
            "extra_images": extra_images,
        })
    except ProductVariant.DoesNotExist:
        return JsonResponse({"error": "Variant not found"}, status=404)


@login_required(login_url=reverse_lazy('accounts:login'))
def wishlist(request):
    # Only keep wishlist items where product still exists
    raw_wishlist = Wishlist.objects.filter(user=request.user).select_related('product')

    # Only include items where product, variant, and size option exist
    wishlist_items = [
        item for item in raw_wishlist
        if item.product
           and item.product.variants.exists()
           and item.product.variants.first().size_options.exists()
    ]

    context = {"w": wishlist_items}
    return render(request, 'wishlist.html', context)


@login_required
@require_POST
def add_to_wishlist(request):
    product_id = request.POST.get('id')
    user = request.user

    try:
        product = Product.objects.get(id=product_id)
        if Wishlist.objects.filter(product=product, user=user).exists():
            return JsonResponse({"bool": False, "message": "Product already in wishlist"})
        else:
            Wishlist.objects.create(product=product, user=user)
            return JsonResponse({"bool": True, "message": "Product added to wishlist"})
    except Product.DoesNotExist:
        return JsonResponse({"bool": False, "message": "Product not found"})


@login_required
def remove_from_wishlist(request, product_id):
    Wishlist.objects.filter(user=request.user, product_id=product_id).delete()
    return HttpResponseRedirect(request.META.get('HTTP_REFERER', '/'))



@require_POST
@login_required
def add_to_cart(request, pid):
    try:
        data = json.loads(request.body)
        product_id = data.get('product_id')
        variant_id = data.get('variant_id')
        selected_size = data.get('size')
        quantity = int(data.get('quantity', 1))

        product = get_object_or_404(Product, pid=product_id)
        cart, _ = Cart.objects.get_or_create(user=request.user, defaults={'total': Decimal('0.00')})

        # Variant Handling
        if variant_id:
            variant = get_object_or_404(ProductVariant, id=variant_id, product=product)
            size_option = variant.size_options.filter(size=selected_size).first()

            if not size_option:
                return JsonResponse({"success": False, "error": "Invalid size for variant"}, status=400)

            if size_option.stock_quantity < quantity:
                return JsonResponse({"success": False, "error": "Insufficient stock"}, status=400)

            cart_item, created = CartItem.objects.get_or_create(
                cart=cart,
                product=product,
                product_variant=variant,
                selected_size=selected_size,
                defaults={'quantity': quantity, 'line_total': size_option.price * quantity}
            )

            if not created:
                if cart_item.quantity + quantity > size_option.stock_quantity:
                    return JsonResponse({"success": False, "error": "Insufficient stock"}, status=400)
                cart_item.quantity += quantity
                cart_item.line_total = cart_item.quantity * size_option.price
                cart_item.save()

        # Main Product Handling
        else:
            size_option = None
            if selected_size:
                size_option = product.size_options.filter(size=selected_size).first()
                if not size_option:
                    return JsonResponse({"success": False, "error": "Invalid size for product"}, status=400)
                price_to_use = size_option.price
                stock_to_check = size_option.stock_quantity
            else:
                price_to_use = product.price
                stock_to_check = product.inventory.stock_quantity

            if stock_to_check < quantity:
                return JsonResponse({"success": False, "error": "Insufficient stock"}, status=400)

            cart_item, created = CartItem.objects.get_or_create(
                cart=cart,
                product=product,
                product_variant=None,
                selected_size=selected_size,
                defaults={'quantity': quantity, 'line_total': price_to_use * quantity}
            )

            if not created:
                if cart_item.quantity + quantity > stock_to_check:
                    return JsonResponse({"success": False, "error": "Insufficient stock"}, status=400)
                cart_item.quantity += quantity
                cart_item.line_total = cart_item.quantity * price_to_use
                cart_item.save()

        # Recalculate cart total
        cart.total = sum(item.line_total for item in cart.cartitem_set.all())
        cart.save()

        return JsonResponse({
            "success": True,
            "total_items": cart.cartitem_set.count(),
            "cart_total": float(cart.total)
        })

    except Exception as e:
        return JsonResponse({"success": False, "error": str(e)}, status=500)


def remove_from_cart(request, item_id):
    try:
        if request.user.is_authenticated:
            item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)
            cart = item.cart  # Get the related cart before deleting
            item.delete()

            # Recalculate and update the cart total
            cart.total = sum(i.line_total for i in cart.cartitem_set.all())
            cart.save()

            messages.success(request, "Item removed from cart.")
        else:
            messages.error(request, "You need to be logged in to remove items from the cart.")
    except CartItem.DoesNotExist:
        messages.error(request, "Item not found in cart.")

    return redirect('products:cart_view')  # or wherever your cart page is


@require_POST
@login_required # Add this decorator if your update_cart_item should require login
def update_cart_item(request):
    try:
        data = json.loads(request.body)
        item_id = data.get('item_id')
        new_quantity = int(data.get('quantity'))

        if new_quantity <= 0:
            return JsonResponse({'success': False, 'error': 'Quantity must be at least 1.'}, status=400)

        cart_item = get_object_or_404(CartItem, id=item_id, cart__user=request.user)

        # --- Determine the correct VariantSizeOption for stock and price ---
        price_to_use = Decimal('0.00')
        stock_to_check = 0
        size_option_obj = None # To hold the found VariantSizeOption object

        if cart_item.product_variant:
            # This path is for products with variants (like your screenshot)
            if not cart_item.selected_size:
                return JsonResponse({'success': False, 'error': 'Size not selected for variant item.'}, status=400)

            size_option_obj = cart_item.product_variant.size_options.filter(size=cart_item.selected_size).first()

            if not size_option_obj:
                return JsonResponse({'success': False, 'error': 'Invalid size option found for variant.'}, status=400)

            price_to_use = size_option_obj.price
            stock_to_check = size_option_obj.stock_quantity

        else:
            # This path is for products without a specific ProductVariant linked to CartItem.
            # Assuming if a product doesn't have a variant, it must still have a default
            # VariantSizeOption linked through its 'variants' relationship if it's sellable.
            # OR, if Product model directly has 'price' and 'stock_quantity' fields,
            # you'd use them here. Based on your model, Product itself doesn't have 'price'
            # or 'inventory.stock_quantity'. This 'else' block might be problematic
            # if non-variant products aren't correctly structured with default variants.
            # If ALL your products eventually have a VariantSizeOption (even a default "One Size"),
            # you might need to adjust how non-variant products are added to the cart
            # to ensure `product_variant` and `selected_size` are always set.

            # Attempt to find a default size option if no variant is attached to CartItem
            # This assumes that even a simple product has at least one variant and size option
            default_variant = cart_item.product.variants.first()
            if default_variant:
                default_size_option = default_variant.size_options.filter(size=cart_item.selected_size).first() # Use selected_size from cart_item
                if not default_size_option:
                     # Fallback to any size option if selected_size doesn't match default variant's size
                    default_size_option = default_variant.size_options.first()

                if default_size_option:
                    size_option_obj = default_size_option
                    price_to_use = size_option_obj.price
                    stock_to_check = size_option_obj.stock_quantity
                else:
                    return JsonResponse({'success': False, 'error': 'No default size option found for product.'}, status=400)
            else:
                 # If product has no variants at all, this implies it's not set up correctly for sale.
                 return JsonResponse({'success': False, 'error': 'Product has no sellable variants.'}, status=400)


        # --- Stock Quantity Check (Applies to both variant and non-variant paths) ---
        if new_quantity > stock_to_check:
            return JsonResponse({
                'success': False,
                'error': f'Insufficient stock. Only {stock_to_check} available.'
            }, status=400)

        # --- Update CartItem ---
        cart_item.quantity = new_quantity
        cart_item.line_total = price_to_use * Decimal(new_quantity)
        cart_item.save()

        # --- Recalculate Cart Totals ---
        cart = cart_item.cart
        # `cart.save()` itself updates `subtotal` and `total` based on items
        # and applies/recalculates discount.
        cart.save()

        # --- Get current discount and shipping for JSON response ---
        discount_amount_for_display = cart.get_discount_amount() if cart.discount_code else Decimal('0.00')
        shipping = SiteSettings.objects.first().shipping_charge if SiteSettings.objects.exists() else Decimal('0.00')
        final_total = cart.total + shipping

        return JsonResponse({
            'success': True,
            'new_line_total': float(cart_item.line_total),
            'cart_subtotal': float(cart.subtotal), # The pre-discount total
            'cart_total_after_discount': float(cart.total), # The discounted product total
            'discount': float(discount_amount_for_display), # The discount amount
            'shipping': float(shipping),
            'final_total': float(final_total) # Grand total including shipping
        })

    except Exception as e:
        # Catch any unexpected errors and log them for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error in update_cart_item for item_id {item_id}, quantity {new_quantity}: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': 'An unexpected error occurred. Please try again.'}, status=500)

@login_required
@csrf_protect
def save_info(request):
    try:
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

                messages.success(request, "Billing and shipping information saved successfully.")
                return redirect('products:checkout')
            else:
                messages.error(request, "There was an error saving your information. Please try again.")
        else:
            billing_form = BillingForm(instance=billing_address)
            shipping_form = ShippingForm(instance=shipping_address)

        context = {
            'billing_form': billing_form,
            'shipping_form': shipping_form,
        }
        return render(request, 'checkout.html', context)
    except Exception as e:
        logger.error(f"Error in save_info process: {e}")
        messages.error(request, 'Error accessing the save info page. Please try again.')
        return redirect('home')


@login_required
@csrf_protect
def checkout(request):
    try:
        cart, _ = Cart.objects.get_or_create(user=request.user,
                                             defaults={'total': Decimal('0.00'), 'subtotal': Decimal('0.00')})

        # IMPORTANT: Ensure the cart's totals (subtotal, total) are up-to-date
        # before retrieving them. The `cart.save()` method in the Cart model
        # handles this. So calling it once here ensures fresh values.
        cart.save()

        items = CartItem.objects.filter(cart=cart)

        if not items.exists():
            messages.error(request, "Your cart is empty. Please add items to your cart before proceeding to checkout.")
            return redirect('products:cart_view')

        billing_address = BillingAddress.objects.filter(user=request.user).first()
        shipping_address = ShippingAddress.objects.filter(user=request.user).first()

        # --- CORRECTED LINE ---
        # Get the discount amount for display. cart.get_discount_amount() does not alter cart.total.
        discount_amount_for_display = cart.get_discount_amount() if cart.discount_code else Decimal('0.00')
        # --- END CORRECTION ---

        shipping = SiteSettings.objects.first().shipping_charge if SiteSettings.objects.exists() else Decimal('0.00')

        # --- CORRECTED LINE ---
        # cart.total already holds the discounted total (from cart.save() above)
        final_total = cart.total + shipping
        # --- END CORRECTION ---

        # Calculate unit price for display on checkout page
        for item in items:
            item.unit_price = item.line_total / item.quantity if item.quantity > 0 else Decimal('0.00')

        if request.method == 'POST' and 'process_payment' in request.POST:
            try:
                # Ensure the final_total is re-evaluated with current cart data
                # (though it should be fresh from cart.save() at the start)
                cart.save()  # Recalculate just in case anything changed
                current_final_total_for_payment = cart.total + shipping
                amount = int(float(current_final_total_for_payment) * 100)  # Razorpay expects amount in paise

                razorpay_order = client.order.create({
                    "amount": amount,
                    "currency": "INR",
                    "payment_capture": "1"
                })

                request.session['razorpay_order_id'] = razorpay_order['id']
                request.session['amount'] = float(amount)  # Store amount in paise

                context = {
                    'razorpay_order_id': razorpay_order['id'],
                    'razorpay_merchant_key': settings.RAZORPAY_KEY_ID,
                    'currency': 'INR',
                    'amount': amount,
                    'billing_address': billing_address,
                    'shipping_address': shipping_address,
                    'callback_url': reverse('products:process_order'),
                }
                return render(request, 'payment.html', context)

            except Exception as e:
                logger.error(f"Exception during Razorpay order creation for user {request.user.id}: {e}")
                messages.error(request, "An error occurred during the payment process. Please try again.")
                return redirect('products:checkout')

        # Prepare forms
        # Assuming BillingForm and ShippingForm are imported
        from .forms import BillingForm, ShippingForm  # Add this import if not already there
        billing_form = BillingForm(instance=billing_address)
        shipping_form = ShippingForm(instance=shipping_address)

        # Prepare context
        context = {
            'cart': cart,
            'items': items,
            'subtotal': cart.subtotal,  # Display the pre-discount total
            'total': cart.total,  # Display the post-discount cart total (before shipping)
            'discount': discount_amount_for_display,  # The calculated discount amount
            'final_total': final_total,  # The grand total including shipping
            'shipping': shipping,
            'billing_form': billing_form,
            'shipping_form': shipping_form,
        }
        return render(request, 'checkout.html', context)

    except Exception as e:
        logger.error(f"Error loading checkout page for user {request.user.id}: {e}")
        messages.error(request, "Error loading checkout page.")
        return redirect('home')


@login_required
@csrf_protect
def process_order(request):
    if request.method == 'POST':
        payment_id = request.POST.get('razorpay_payment_id')
        razorpay_order_id = request.POST.get('razorpay_order_id')
        signature = request.POST.get('razorpay_signature')

        if not payment_id or not razorpay_order_id or not signature:
            messages.error(request, "Payment was canceled or details are missing.")
            return redirect('products:cart_view')

        params_dict = {
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': payment_id,
            'razorpay_signature': signature
        }

        try:
            client.utility.verify_payment_signature(params_dict)

            payment_details = client.payment.fetch(payment_id)
            payment_method = payment_details['method']

            user = request.user
            cart = Cart.objects.get(user=user)

            # Ensure cart's totals are up-to-date just before creating order
            cart.save()

            billing_address = BillingAddress.objects.filter(user=user).first()
            shipping_address = ShippingAddress.objects.filter(user=user).first()

            if not billing_address:
                logger.error(f"Error processing order for user {user.id}: Billing address missing.")
                messages.error(request,
                               "Your billing information is missing. Please update it before placing the order.")
                return redirect('products:checkout')

            if not shipping_address:
                logger.error(f"Error processing order for user {user.id}: Shipping address missing.")
                messages.error(request,
                               "Your shipping information is missing. Please update it before placing the order.")
                return redirect('products:checkout')

            # --- CORRECTED LINE ---
            # Get the discount amount for the order record (it's already factored into cart.total)
            discount_amount_for_order = cart.get_discount_amount() if cart.discount_code else Decimal('0.00')
            # --- END CORRECTION ---
            discount_code_value = cart.discount_code.code if cart.discount_code else None

            with transaction.atomic():
                items = CartItem.objects.filter(cart=cart)

                for item in items:
                    if item.product_variant:
                        variant_size = item.product_variant.size_options.filter(size=item.selected_size).first()
                        if not variant_size or item.quantity > variant_size.stock_quantity:
                            messages.error(request,
                                           f"Insufficient stock for {item.product_variant.color} - {item.selected_size}.")
                            transaction.set_rollback(True)  # Rollback in case of stock issue
                            return redirect('products:cart_view')
                        price = variant_size.price
                    else:
                        # Assuming product.stock_quantity exists directly on Product model
                        if not hasattr(item.product, 'stock_quantity') or item.quantity > item.product.stock_quantity:
                            messages.error(request, f"Insufficient stock for {item.product.name}.")
                            transaction.set_rollback(True)
                            return redirect('products:cart_view')
                        price = item.product.price

                order = Order.objects.create(
                    user=user,
                    billing_full_name=billing_address.billing_full_name,
                    billing_email=billing_address.billing_email,
                    billing_address1=billing_address.billing_address1,
                    billing_address2=billing_address.billing_address2,
                    billing_city=billing_address.billing_city,
                    billing_state=billing_address.billing_state,
                    billing_zipcode=billing_address.billing_zipcode,
                    billing_country=billing_address.billing_country,
                    billing_phone=billing_address.billing_phone,
                    shipping_full_name=shipping_address.shipping_full_name,
                    shipping_email=shipping_address.shipping_email,
                    shipping_address1=shipping_address.shipping_address1,
                    shipping_address2=shipping_address.shipping_address2,
                    shipping_city=shipping_address.shipping_city,
                    shipping_state=shipping_address.shipping_state,
                    shipping_zipcode=shipping_address.shipping_zipcode,
                    shipping_country=shipping_address.shipping_country,
                    shipping_phone=shipping_address.shipping_phone,
                    total=cart.total,  # cart.total already holds the discounted amount
                    payment_method=payment_method,
                    discount=discount_amount_for_order,  # Use the calculated discount amount for the order record
                    discount_code=discount_code_value,
                )

                for item in items:
                    # Determine the correct price for the order item based on variant/product
                    if item.product_variant:
                        variant_size = item.product_variant.size_options.filter(size=item.selected_size).first()
                        item_price_at_order = variant_size.price
                    else:
                        item_price_at_order = item.product.price  # Assuming Product has 'price' if no variant

                    OrderItem.objects.create(
                        order=order,
                        product=item.product,
                        product_variant=item.product_variant,
                        user=user,
                        quantity=item.quantity,
                        price=item_price_at_order,  # Use the price at the time of order creation
                        selected_size=item.selected_size
                    )

                    # Update stock
                    if item.product_variant:
                        variant_size.stock_quantity -= item.quantity
                        variant_size.save()
                    else:
                        # Assuming product.stock_quantity exists directly on Product model
                        if hasattr(item.product, 'stock_quantity'):
                            item.product.stock_quantity -= item.quantity
                            item.product.save()

                    item.delete()  # Remove item from cart

                cart.subtotal = Decimal('0.00')  # Reset subtotal
                cart.total = Decimal('0.00')  # Reset total
                cart.discount_code = None  # Clear discount
                cart.save()

                send_order_email(request, order.id)

            messages.success(request, "Your order has been placed successfully.")
            return redirect('products:order_tracking')

        except razorpay.errors.SignatureVerificationError:
            messages.error(request, "Payment verification failed. Please try again.")
            return redirect('products:cart_view')
        except Exception as e:
            logger.error(f"Error placing order for user {user.id}: {e}",
                         exc_info=True)  # exc_info=True for full traceback
            messages.error(request, "An error occurred during the payment process. Please try again.")
            return redirect('products:cart_view')

    return redirect('home')


@login_required
@csrf_protect
def place_order_cod(request):
    if request.method == 'POST':
        try:
            user = request.user
            cart = Cart.objects.get(user=user)

            # Ensure cart's totals are up-to-date just before creating order
            cart.save()

            items = CartItem.objects.filter(cart=cart)

            if not items.exists():
                messages.error(request, "Your cart is empty. Please add items before placing an order.")
                return redirect('products:checkout')

            billing_address = BillingAddress.objects.filter(user=user).first()
            shipping_address = ShippingAddress.objects.filter(user=user).first()

            if not billing_address:
                logger.error(f"Error processing COD order for user {user.id}: Billing address missing.")
                messages.error(request,
                               "Your billing information is missing. Please update it before placing the order.")
                return redirect('products:checkout')

            if not shipping_address:
                logger.error(f"Error processing COD order for user {user.id}: Shipping address missing.")
                messages.error(request,
                               "Your shipping information is missing. Please update it before placing the order.")
                return redirect('products:checkout')

            # --- CORRECTED LINE ---
            discount_amount_for_order = cart.get_discount_amount() if cart.discount_code else Decimal('0.00')
            # --- END CORRECTION ---
            discount_code_value = cart.discount_code.code if cart.discount_code else None

            with transaction.atomic():
                for item in items:
                    if item.product_variant:
                        variant_size = item.product_variant.size_options.filter(size=item.selected_size).first()
                        if not variant_size or item.quantity > variant_size.stock_quantity:
                            messages.error(request,
                                           f"Insufficient stock for {item.product_variant.color} - {item.selected_size}.")
                            transaction.set_rollback(True)
                            return redirect('products:cart_view')
                        price = variant_size.price
                    else:
                        # Assuming product.stock_quantity exists directly on Product model
                        if not hasattr(item.product, 'stock_quantity') or item.quantity > item.product.stock_quantity:
                            messages.error(request, f"Insufficient stock for {item.product.name}.")
                            transaction.set_rollback(True)
                            return redirect('products:cart_view')
                        price = item.product.price

                order = Order.objects.create(
                    user=user,
                    billing_full_name=billing_address.billing_full_name,
                    billing_email=billing_address.billing_email,
                    billing_address1=billing_address.billing_address1,
                    billing_address2=billing_address.billing_address2,
                    billing_city=billing_address.billing_city,
                    billing_state=billing_address.billing_state,
                    billing_zipcode=billing_address.billing_zipcode,
                    billing_country=billing_address.billing_country,
                    billing_phone=billing_address.billing_phone,
                    shipping_full_name=shipping_address.shipping_full_name,
                    shipping_email=shipping_address.shipping_email,
                    shipping_address1=shipping_address.shipping_address1,
                    shipping_address2=shipping_address.shipping_address2,
                    shipping_city=shipping_address.shipping_city,
                    shipping_state=shipping_address.shipping_state,
                    shipping_zipcode=shipping_address.shipping_zipcode,
                    shipping_country=shipping_address.shipping_country,
                    shipping_phone=shipping_address.shipping_phone,
                    total=cart.total,  # cart.total already holds the discounted amount
                    payment_method="Cash on Delivery",
                    status="pending",
                    discount=discount_amount_for_order,  # Use the calculated discount amount for the order record
                    discount_code=discount_code_value,
                )

                for item in items:
                    # Determine the correct price for the order item based on variant/product
                    if item.product_variant:
                        variant_size = item.product_variant.size_options.filter(size=item.selected_size).first()
                        item_price_at_order = variant_size.price
                    else:
                        item_price_at_order = item.product.price  # Assuming Product has 'price' if no variant

                    OrderItem.objects.create(
                        order=order,
                        product=item.product,
                        product_variant=item.product_variant,
                        user=user,
                        quantity=item.quantity,
                        price=item_price_at_order,  # Use the price at the time of order creation
                        selected_size=item.selected_size
                    )

                    # Update stock
                    if item.product_variant:
                        variant_size.stock_quantity -= item.quantity
                        variant_size.save()
                    else:
                        # Assuming product.stock_quantity exists directly on Product model
                        if hasattr(item.product, 'stock_quantity'):
                            item.product.stock_quantity -= item.quantity
                            item.product.save()

                    item.delete()  # Remove item from cart

                cart.subtotal = Decimal('0.00')  # Reset subtotal
                cart.total = Decimal('0.00')  # Reset total
                cart.discount_code = None  # Clear discount
                cart.save()

                send_order_email(request, order.id)

            messages.success(request, "Your order has been placed successfully under Cash on Delivery.")
            return redirect('products:order_tracking')

        except Exception as e:
            logger.error(f"Error placing COD order for user {user.id}: {e}", exc_info=True)
            messages.error(request, "An error occurred while placing your order. Please try again.")
            return redirect('products:checkout')

    return redirect('home')


@csrf_exempt
def razorpay_webhook(request):
    try:
        webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
        received_signature = request.headers.get('X-Razorpay-Signature')
        body = request.body

        # Signature validation
        generated_signature = hmac.new(
            webhook_secret.encode(),
            msg=body,
            digestmod=hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(received_signature, generated_signature):
            return HttpResponse(status=403)

        data = json.loads(body)
        event = data.get('event')

        if event == "payment.captured":
            payment_entity = data['payload']['payment']['entity']
            razorpay_order_id = payment_entity.get('order_id')
            payment_id = payment_entity.get('id')
            method = payment_entity.get('method')

            amount = Decimal(payment_entity.get('amount', 0)) / 100

            try:
                cart = Cart.objects.get(razorpay_order_id=razorpay_order_id)
                user = cart.user
                items = CartItem.objects.filter(cart=cart)

                billing_address = BillingAddress.objects.filter(user=user).first()
                shipping_address = ShippingAddress.objects.filter(user=user).first()

                with transaction.atomic():
                    for item in items:
                        if item.product_variant and item.quantity > item.product_variant.stock_quantity:
                            return HttpResponse("Insufficient stock", status=400)
                        elif not item.product_variant and item.quantity > item.product.stock_quantity:
                            return HttpResponse("Insufficient stock", status=400)

                    order = Order.objects.create(
                        user=user,
                        billing_full_name=billing_address.billing_full_name,
                        billing_email=billing_address.billing_email,
                        billing_address1=billing_address.billing_address1,
                        billing_address2=billing_address.billing_address2,
                        billing_city=billing_address.billing_city,
                        billing_state=billing_address.billing_state,
                        billing_zipcode=billing_address.billing_zipcode,
                        billing_country=billing_address.billing_country,
                        billing_phone=billing_address.billing_phone,
                        shipping_full_name=shipping_address.shipping_full_name,
                        shipping_email=shipping_address.shipping_email,
                        shipping_address1=shipping_address.shipping_address1,
                        shipping_address2=shipping_address.shipping_address2,
                        shipping_city=shipping_address.shipping_city,
                        shipping_state=shipping_address.shipping_state,
                        shipping_zipcode=shipping_address.shipping_zipcode,
                        shipping_country=shipping_address.shipping_country,
                        shipping_phone=shipping_address.shipping_phone,
                        total=cart.total,
                        payment_method=method
                    )

                    for item in items:
                        OrderItem.objects.create(
                            order=order,
                            product=item.product,
                            product_variant=item.product_variant if item.product_variant else None,
                            user=user,
                            quantity=item.quantity,
                            price=item.product_variant.price if item.product_variant else item.product.price
                        )

                        if item.product_variant:
                            item.product_variant.stock_quantity -= item.quantity
                            item.product_variant.save()
                        else:
                            item.product.stock_quantity -= item.quantity
                            item.product.save()

                        item.delete()

                    cart.total = Decimal('0.00')
                    cart.razorpay_order_id = None
                    cart.save()

                    send_order_email(request, order.id)

                    return HttpResponse(status=200)

            except Exception as e:
                return HttpResponse(f"Order processing error: {str(e)}", status=500)

        return HttpResponse(status=400)

    except Exception as e:
        return HttpResponse(f"Webhook error: {str(e)}", status=500)

@login_required
def check_payment_status(request):
    try:
        cart = Cart.objects.get(user=request.user)

        # Look for the latest order created with the cart's total
        order_exists = Order.objects.filter(user=request.user).order_by('-created_at').first()

        if order_exists and order_exists.total == cart.total:
            return JsonResponse({'status': 'completed'})

        return JsonResponse({'status': 'pending'})
    except:
        return JsonResponse({'status': 'error'})


def payment_failed(request):
    return render(request, 'products/payment_failed.html')  # Customize this template



@login_required
def send_order_email(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    items = OrderItem.objects.filter(order=order)

    billing_address = BillingAddress.objects.filter(user=request.user).first()
    shipping_address = ShippingAddress.objects.filter(user=request.user).first()

    site_settings = SiteSettings.objects.first()
    shipping_charge = site_settings.shipping_charge if site_settings else Decimal('0.00')
    final_total = order.total + shipping_charge  # `order.total` is discounted product total, this is grand total

    invoice_link = request.build_absolute_uri(reverse('products:order_invoice', args=[order.id]))

    subject = f" Your Order Confirmation with Stellars - Order #{order.order_id}"
    html_content = render_to_string('order_email.html', {
        'order': order,
        'items': items,
        'billing_address': billing_address,
        'shipping_address': shipping_address,
        'shipping_charge': shipping_charge,
        'final_total': final_total,
        'user': request.user,
        'invoice_link': invoice_link,
    })
    text_content = strip_tags(html_content)
    from_email = settings.DEFAULT_FROM_EMAIL
    to_email = ['stellarspvt@gmail.com', request.user.email]

    email = EmailMultiAlternatives(subject, text_content, from_email, to_email)
    email.attach_alternative(html_content, "text/html")
    email.send()

    return JsonResponse({'success': True, 'message': 'Email sent successfully'})


@login_required(login_url=reverse_lazy('accounts:login'))
def order_tracking(request):
    user_orders = Order.objects.filter(user=request.user)
    # --- ADD THIS DEBUG LINE ---
    for order in user_orders:
        print(f"Order ID: {order.order_id}, Tracking ID: {order.tracking_id}, Tracking URL: {order.tracking_url}")
    # ---------------------------
    context = {'orders': user_orders}
    return render(request, 'order_tracking2.html', context)

@csrf_exempt
def update_order_status(request):
    if request.method == 'POST':
        order_id = request.POST.get('order_id')
        status = request.POST.get('status')
        order = get_object_or_404(Order, id=order_id, user=request.user)
        order.status = status
        order.save()
        return JsonResponse({'success': True})
    return JsonResponse({'success': False})


def order_details(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    items = OrderItem.objects.filter(order=order)

    can_cancel = order.status in ['pending', 'processing', 'shipped']

    context = {
        'order': order,
        'items': items,
        'billing_address': {
            'full_name': order.billing_full_name,
            'email': order.billing_email,
            'address1': order.billing_address1,
            'address2': order.billing_address2,
            'city': order.billing_city,
            'state': order.billing_state,
            'zipcode': order.billing_zipcode,
            'country': order.billing_country,
            'phone': order.billing_phone,
        },
        'shipping_address': {
            'full_name': order.shipping_full_name,
            'email': order.shipping_email,
            'address1': order.shipping_address1,
            'address2': order.shipping_address2,
            'city': order.shipping_city,
            'state': order.shipping_state,
            'zipcode': order.shipping_zipcode,
            'country': order.shipping_country,
            'phone': order.shipping_phone,
        },
        'final_total': order.total,
        'user': request.user,
        'can_cancel': can_cancel,  # Pass the boolean to the template

    }
    return render(request, 'order_details.html', context)


def generate_product_qr_code_base64(request, product_pid):
    """
    Generates a QR code for a product's detail page and returns it as a base64 data URL.
    """
    try:
        # Construct the absolute URL to the product detail page
        product_url = request.build_absolute_uri(reverse('products:product_details', args=[product_pid]))

        # Create QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=4,  # Adjust size as needed, 4-6 is usually good for invoices
            border=2,  # Border around the QR code
        )
        qr.add_data(product_url)
        qr.make(fit=True)

        # Create an image from the QR Code instance
        img = qr.make_image(fill_color="black", back_color="white").convert('RGB')

        # Save image to a BytesIO object
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        img_str = base64.b64encode(buffer.getvalue()).decode("utf-8")

        # Return as a data URL
        return f"data:image/png;base64,{img_str}"
    except Exception as e:
        # Log any errors (e.g., product_pid not found, image generation issue)
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error generating QR code for product_pid {product_pid}: {e}", exc_info=True)
        return None  # Return None if generation fails


# --- Modify order_invoice view ---
@login_required
def order_invoice(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    items = OrderItem.objects.filter(order=order)

    # Order.total already stores the discounted product total (including tax).
    # Order.discount stores the absolute discount amount that was applied.

    actual_discount_amount = order.discount or Decimal('0.00')
    discount_code_value = order.discount_code or None

    shipping_charge = SiteSettings.objects.first().shipping_charge if SiteSettings.objects.exists() else Decimal('0.00')

    # --- REVISED CALCULATIONS (as per previous correction) ---
    product_total_after_discount_and_inclusive_tax = order.total
    tax_rate = Decimal('0.18')
    product_total_excluding_tax = product_total_after_discount_and_inclusive_tax / (Decimal('1') + tax_rate)
    tax_amount = product_total_after_discount_and_inclusive_tax - product_total_excluding_tax
    grand_total_to_pay = product_total_after_discount_and_inclusive_tax + shipping_charge
    shipping_state = order.shipping_state.strip().lower()
    is_interstate = shipping_state != "maharashtra".lower()

    # --- NEW: Generate QR code for each item ---
    for item in items:
        # The product object associated with the OrderItem
        product_obj = item.product
        if product_obj:
            item.qr_code_data = generate_product_qr_code_base64(request, product_obj.pid)
        else:
            item.qr_code_data = None # No QR if product link is not valid

    context = {
        'order': order,
        'items': items, # items now have 'qr_code_data' attribute
        'billing_address': {
            'full_name': order.billing_full_name,
            'email': order.billing_email,
            'address1': order.billing_address1,
            'address2': order.billing_address2 or '',
            'city': order.billing_city,
            'state': order.billing_state,
            'zipcode': order.billing_zipcode,
            'country': order.billing_country,
            'phone': order.billing_phone,
        },
        'shipping_address': {
            'full_name': order.shipping_full_name,
            'email': order.shipping_email,
            'address1': order.shipping_address1,
            'address2': order.shipping_address2 or '',
            'city': order.shipping_city,
            'state': order.shipping_state,
            'zipcode': order.shipping_zipcode,
            'country': order.shipping_country,
            'phone': order.shipping_phone,
        },
        'actual_discount_amount': actual_discount_amount,
        'discount_code': discount_code_value,
        'shipping_charge': shipping_charge,
        'tax_amount': tax_amount,
        'product_total_excluding_tax': product_total_excluding_tax,
        'product_total_after_discount_and_inclusive_tax': product_total_after_discount_and_inclusive_tax,
        'grand_total_to_pay': grand_total_to_pay,
        'is_interstate': is_interstate,
    }

    return render(request, 'invoice_temp.html', context)

def request_order_cancel(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)

    if request.method == 'POST':
        # Process the cancellation form
        cancellation_reason = request.POST.get('cancellation_reason')
        other_text = request.POST.get('other_text', '').strip()
        reason = f"{cancellation_reason}: {other_text}" if cancellation_reason == "Other" and other_text else cancellation_reason

        if order.status in ['pending', 'processing', 'shipped']:
            order.status = 'cancelled'
            order.feedback_note = reason  # Save the cancellation reason
            order.cancel_requested = True
            order.save()

            send_order_cancellation_email(order, reason)

            messages.success(request, "Your order has been cancelled successfully.")
            return redirect('products:order_tracking')
        else:
            messages.error(request, "Order cannot be cancelled at this stage.")
            return redirect('products:order_details', order_id=order.id)

    # Display the cancellation form
    return render(request, 'order_cancel_form.html', {'order': order})

@login_required
def request_order_return(request, order_id):
    if request.method == 'POST':
        order = get_object_or_404(Order, id=order_id, user=request.user)
        return_deadline = order.updated_at + timedelta(days=7)

        # Check if the order is eligible for return
        if order.status == 'delivered' and order.updated_at <= return_deadline:
            order.return_requested = True
            order.status = 'returned'
            order.save()

            # Send email notifications
            return JsonResponse({'success': True, 'message': 'Return request processed successfully.'})
        else:
            return JsonResponse({'success': False, 'message': 'Return period has expired or order not delivered yet.'})
    else:
        return JsonResponse({'success': False, 'message': 'Invalid request method.'})



@login_required
def request_order_replace(request, order_id):
    if request.method == 'POST':
        order = get_object_or_404(Order, id=order_id, user=request.user)
        replace_deadline = order.updated_at + timedelta(days=7)

        # Check if the order is eligible for replacement
        if order.status == 'delivered' and order.updated_at <= replace_deadline:
            order.replace_requested = True
            order.status = 'replaced'
            order.save()

            # Send email notifications
            return JsonResponse({'success': True, 'message': 'Replacement request processed successfully.'})
        else:
            return JsonResponse({'success': False, 'message': 'Replacement period has expired or order not delivered yet.'})
    else:
        return JsonResponse({'success': False, 'message': 'Invalid request method.'})


@login_required
def request_order_complete(request, order_id):
    if request.method == 'POST':
        order = get_object_or_404(Order, id=order_id, user=request.user)

        # Check if order is eligible to be marked as complete
        if order.status == 'delivered':
            order.status = 'completed'  # Make sure this status is valid in your model
            order.save()
            return JsonResponse({'success': True, 'message': 'Order marked as complete successfully.'})
        else:
            return JsonResponse({'success': False, 'message': 'Order cannot be completed at this stage.'})
    else:
        return JsonResponse({'success': False, 'message': 'Invalid request method.'})


@login_required
def request_order_action(request, order_id, action):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    action_lower = action.lower()

    if request.method == 'POST':
        form = FeedbackForm(request.POST)
        if form.is_valid():
            feedback_note = form.cleaned_data['feedback_note']
            order.feedback_note = feedback_note

            # Process the return or replace actions
            if action_lower == 'return' and order.status == 'delivered':
                order.status = 'returned'
                order.return_requested = True
            elif action_lower == 'replace' and order.status == 'delivered':
                order.status = 'replaced'
                order.replace_requested = True
            else:
                messages.error(request, "Invalid action or order status.")
                return redirect('products:order_details', order_id=order.id)

            order.save()

            # Send feedback email to user and custom_admin with the action
            send_feedback_email(order, feedback_note, action_lower)

            messages.success(request, f"Your {action} request has been processed successfully.")
            return redirect('products:order_tracking')
    else:
        form = FeedbackForm()

    return render(request, 'order_feedback.html', {
        'form': form,
        'order': order,
        'action': action.capitalize(),
        'action_lower': action_lower,
    })



# send email when order is cancel return and replaced


def send_order_cancellation_email(order, reason):
    # Prepare email content for the user
    user_subject = "Your Order Has Been Cancelled"
    user_email_template = 'user_order_canceled.html'
    user_email_content = render_to_string(user_email_template, {
        'user': order.user,
        'order': order,
        'reason': reason,
    })

    # Prepare email content for the custom_admin
    admin_subject = "Order Cancellation Notification"
    admin_email_template = 'admin_order_canceled.html'
    admin_email_content = render_to_string(admin_email_template, {
        'user': order.user,
        'order': order,
        'reason': reason,
    })

    # Send email to the user
    send_mail(
        subject=user_subject,
        message="",
        html_message=user_email_content,
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[order.user.email],
        fail_silently=False,
    )

    # Send email to the custom_admin
    admin_email = settings.EMAIL_HOST_USER  # Admin's email address
    send_mail(
        subject=admin_subject,
        message="",
        html_message=admin_email_content,
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[admin_email],
        fail_silently=False,
    )


def send_feedback_email(order, feedback_note, action):
    action_capitalized = action.capitalize()

    # Determine subject and templates based on action
    if action == 'return':
        user_subject = f"Return Request Received for Order #{order.id}"
        admin_subject = f"New Return Request for Order #{order.id}"
        user_email_template = 'email/user_return_feedback.html'
        admin_email_template = 'email/admin_return_feedback.html'
    elif action == 'replace':
        user_subject = f"Replacement Request Received for Order #{order.id}"
        admin_subject = f"New Replacement Request for Order #{order.id}"
        user_email_template = 'email/user_replace_feedback.html'
        admin_email_template = 'email/admin_replace_feedback.html'
    else:
        user_subject = f"Feedback Received for Order #{order.id}"
        admin_subject = f"New Feedback for Order #{order.id}"
        user_email_template = 'email/user_feedback.html'
        admin_email_template = 'email/admin_feedback.html'

    # Render email content
    user_email_content = render_to_string(user_email_template, {
        'user': order.user,
        'order': order,
        'feedback_note': feedback_note,
        'action': action_capitalized,
    })
    user_text_content = strip_tags(user_email_content)

    admin_email_content = render_to_string(admin_email_template, {
        'user': order.user,
        'order': order,
        'feedback_note': feedback_note,
        'action': action_capitalized,
    })
    admin_text_content = strip_tags(admin_email_content)

    # Send email to the user
    send_mail(
        subject=user_subject,
        message=user_text_content,
        html_message=user_email_content,
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[order.user.email],
        fail_silently=False,
    )

    # Send email to the custom_admin
    admin_email = settings.EMAIL_HOST_USER  # Replace with actual custom_admin email if different
    send_mail(
        subject=admin_subject,
        message=admin_text_content,
        html_message=admin_email_content,
        from_email=settings.EMAIL_HOST_USER,
        recipient_list=[admin_email],
        fail_silently=False,
    )



def product_dashboard(request):
    return render(request, 'product_dashboard.html')


def product_services(request):
    return render(request, 'products-services.html')

def hyperdeckcontroller(request):
    return render(request, 'hyperdeckcontroller.html')

def about(request):
    about_content = About.objects.first()
    return render(request, 'about.html', {'about_content': about_content})

def delivery_info(request):
    return render(request, 'information/delivery_info.html')

def privacy_policy(request):
    return render(request, 'information/privacy_policy.html')

def return_refund(request):
    return render(request, 'information/return_refund.html')

def terms_condition(request):
    return render(request, 'information/terms_condition.html')


def faq(request):
    return render(request, 'information/faq.html')



def global_search_view(request):
    query = request.GET.get('q', '').strip().lower()

    if not query:
        return JsonResponse({'status': 'empty', 'message': 'Empty search query'}, status=400)

    product = Product.objects.filter(name__iexact=query).first()
    if product:
        return JsonResponse({'status': 'redirect', 'url': reverse('products:product_details', args=[product.pid])})

    main_category = MainCategory.objects.filter(title__iexact=query).first()
    if main_category:
        return JsonResponse({'status': 'redirect', 'url': reverse('products:product_grid_by_main_category', args=[main_category.cid])})

    sub_category = SubCategory.objects.filter(title__iexact=query).first()
    if sub_category:
        return JsonResponse({'status': 'redirect', 'url': reverse('products:product_grid_by_sub_category', args=[sub_category.sid])})

    blog = Blog.objects.filter(title__iexact=query).first()
    if blog:
        return JsonResponse({'status': 'redirect', 'url': blog.get_absolute_url()})

    static_pages = {
        'about us': reverse('products:about'),
        'terms and conditions': reverse('products:terms_condition'),
        'privacy policy': reverse('products:privacy_policy'),
        'return and refund': reverse('products:return_refund'),
        'delivery information': reverse('products:delivery_info'),
    }
    if query in static_pages:
        return JsonResponse({'status': 'redirect', 'url': static_pages[query]})

    if request.user.is_authenticated:
        try:
            order = Order.objects.get(user=request.user, id=int(query))
            return JsonResponse({'status': 'redirect', 'url': reverse('products:order_details', args=[order.id])})
        except (Order.DoesNotExist, ValueError):
            pass

    return JsonResponse({'status': 'not_found', 'message': 'No matching result found.'})


def claim_discount(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        phone = request.POST.get('phone')
        email = request.POST.get('email')

        coupon_code = 'WELCOME10'  # You can also randomize if needed

        # Save to Database
        DiscountLead.objects.create(
            name=name,
            phone=phone,
            email=email,
            coupon_code=coupon_code
        )

        # Prepare Email Content
        subject = '🎉 Here’s Your 10% OFF Coupon Code!'
        plain_message = f"""
Hello {name},

Thank you for signing up with us!

Here is your 10% OFF Coupon Code: {coupon_code}

Apply this code during checkout to enjoy your discount.

Happy Shopping!

- YourCompany Team
"""

        html_message = f"""
<html>
<body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f4f4f4;">
  <div style="max-width: 600px; margin: auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">
    <h2 style="color: #2E8B57;">Hello {name},</h2>
    <p style="font-size: 16px;">Thank you for signing up with us!</p>
    <p style="font-size: 18px; margin: 20px 0;">🎁 Your <strong>10% OFF Coupon Code</strong> is:</p>
    <div style="background: #2E8B57; color: white; padding: 15px; font-size: 24px; border-radius: 5px; letter-spacing: 2px; margin: 20px 0;">
      {coupon_code}
    </div>
    <p style="font-size: 16px;">Use this code at checkout and enjoy your discount!</p>
    <p style="font-size: 14px; color: #888; margin-top: 30px;">Happy Shopping!<br><strong>YourCompany Team</strong></p>
  </div>
</body>
</html>
"""

        from_email = settings.DEFAULT_FROM_EMAIL
        recipient_list = [email]

        try:
            send_mail(
                subject,
                plain_message,
                from_email,
                recipient_list,
                html_message=html_message
            )
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)})

        # Optional: Set session so the discount is auto applied
        # request.session['applied_coupon_code'] = coupon_code

        return JsonResponse({'success': True})

    return JsonResponse({'success': False, 'error': 'Invalid request method'})

