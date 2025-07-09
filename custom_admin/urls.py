from django.urls import path
from django.contrib.auth.views import LoginView
from . import views
from django.contrib.auth.views import LogoutView
from .views import main_categories_view, add_main_category_view, edit_main_category_view, delete_main_category_view, \
    subcategories_view, add_subcategory_view, edit_subcategory_view, delete_subcategory_view, product_list_view, \
    add_product_view, edit_product_view, delete_product_view, \
    variant_list_view, add_variant_view, edit_variant_view, delete_variant_view
from django.conf.urls.static import static
from django.conf import settings


app_name = 'custom_admin'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),  # Default route for the custom admin panel
    path('api/daily-sales/', views.daily_sales_data, name='daily_sales_data'),  # Daily sales API
    path('api/weekly-orders/', views.weekly_order_data, name='weekly_order_data'),
    path('api/monthly-sales/', views.monthly_sales_data, name='monthly_sales_data'),
    path('export-orders-excel/', views.export_orders_excel, name='export_orders_excel'),
    path('export_orders_summary_excel/', views.export_orders_summary_excel, name='export_orders_summary_excel'),

    #path('login/', LoginView.as_view(template_name='admin/login1.html'), name='admin_login'),
    path('login/', views.admin_login_view, name='admin_login'),

    path('logout/', LogoutView.as_view(), name='admin_logout'),

    path('media-library/', views.media_library_view, name='media_library'),
    path('media-library/delete/<int:pk>/', views.delete_media_file, name='delete_media'),

    path('main-categories/', main_categories_view, name='main_categories'),
    path('main-categories/add/', add_main_category_view, name='add_main_category'),
    path('main-categories/edit/<int:pk>/', edit_main_category_view, name='edit_main_category'),
    path('main-categories/delete/<int:pk>/', delete_main_category_view, name='delete_main_category'),
    path('main-categories/upload/', views.upload_main_categories_view, name='upload_main_categories_view'),

    path('subcategories/', subcategories_view, name='subcategories'),
    path('subcategories/add/', add_subcategory_view, name='add_subcategory'),
    path('subcategories/edit/<int:pk>/', edit_subcategory_view, name='edit_subcategory'),
    path('subcategories/delete/<int:pk>/', delete_subcategory_view, name='delete_subcategory'),
    path('subcategories/upload/', views.upload_subcategories_view, name='upload_subcategories_view'),


    path('products/', product_list_view, name='product_list'),
    path('products/add/', add_product_view, name='add_product'),
    path('products/edit/<int:pk>/', edit_product_view, name='edit_product'),
    path('products/delete/<int:pk>/', delete_product_view, name='delete_product'),
    path('products/upload/', views.upload_products_view, name='upload_products'),


    path('variants/', variant_list_view, name='variant_list'),
    path("variants/add/", views.add_variant_view, name="add_variant"),
    path('variants/edit/<int:pk>/', edit_variant_view, name='edit_variant'),
    path('variants/delete/<int:pk>/', delete_variant_view, name='delete_variant'),
    path('variants/upload/', views.upload_variants_view, name='upload_variants'),

                  # urls.py
    path('variant/<str:variant_id>/label/<str:size>/', views.generate_variant_label, name='generate_variant_label'),
    path('variants/generate-all-tags/', views.generate_all_variant_labels, name='generate_all_variant_labels'),

    path('site-settings/', views.site_settings_list, name='site_settings_list'),
    path('site-settings/create/', views.site_settings_create, name='site_settings_create'),
    path('site-settings/update/<int:pk>/', views.site_settings_update, name='site_settings_update'),
    path('site-settings/delete/<int:pk>/', views.site_settings_delete, name='site_settings_delete'),

    path('orders/', views.order_list_view, name='order_list'),
    path('orders/add/', views.add_order_view, name='add_order'),
    path('orders/edit/<int:pk>/', views.edit_order_view, name='edit_order'),
    path('orders/delete/<int:pk>/', views.delete_order_view, name='delete_order'),
    path('orders/<int:pk>/update-status/', views.update_order_status_view, name='update_order_status'),

    path('cart/', views.cart_list_view, name='cart_list'),
    path('cart/add/', views.add_cart_view, name='add_cart'),
    path('cart/edit/<int:pk>/', views.edit_cart_view, name='edit_cart'),
    path('cart/delete/<int:pk>/', views.delete_cart_view, name='delete_cart'),

    path('wishlist/', views.wishlist_list_view, name='wishlist_list'),
    path('wishlist/add/', views.add_wishlist_view, name='add_wishlist'),
    path('wishlist/edit/<int:pk>/', views.edit_wishlist_view, name='edit_wishlist'),
    path('wishlist/delete/<int:pk>/', views.delete_wishlist_view, name='delete_wishlist'),

    path('user/<int:user_id>/addresses/', views.user_addresses_view, name='user_addresses'),

    path('blogs/', views.blog_list_view, name='blog_list'),
    path('blogs/add/', views.add_blog_view, name='add_blog'),
    path('blogs/edit/<int:pk>/', views.edit_blog_view, name='edit_blog'),
    path('blogs/delete/<int:pk>/', views.delete_blog_view, name='delete_blog'),

    path('banners/', views.banner_list_view, name='banner_list'),
    path('banners/add/', views.add_banner_view, name='add_banner'),
    path('banners/edit/<int:pk>/', views.edit_banner_view, name='edit_banner'),
    path('banners/delete/<int:pk>/', views.delete_banner_view, name='delete_banner'),

    path('customers/', views.customer_list_view, name='customer_list'),
    path('customers/add/', views.add_customer_view, name='add_customer'),
    path('customers/edit/<int:pk>/', views.edit_customer_view, name='edit_customer'),
    path('customers/delete/<int:pk>/', views.delete_customer_view, name='delete_customer'),

    path('about/', views.about_list_view, name='about_list'),
    path('about/add/', views.add_about_view, name='add_about'),
    path('about/edit/<int:pk>/', views.edit_about_view, name='edit_about'),
    path('about/delete/<int:pk>/', views.delete_about_view, name='delete_about'),

    path('user-management/', views.user_list_view, name='user_list'),
    path('user-management/<int:user_id>/edit/', views.edit_user_role, name='edit_user_role'),
    path('profile/', views.profile_view, name='profile'),
    path('main-category/add/', views.add_main_category_view, name='add_main_category'),

    path('coupons/', views.coupon_list_view, name='coupon_list'),
    path('coupons/add/', views.add_coupon_view, name='add_coupon'),
    path('coupons/edit/<int:pk>/', views.edit_coupon_view, name='edit_coupon'),
    path('coupons/delete/<int:pk>/', views.delete_coupon_view, name='delete_coupon'),


    path('dashboard/download/weekly-order/', views.download_weekly_order_report, name='download_weekly_order_report'),
    path('dashboard/download/daily-sales/', views.download_daily_sales_report, name='download_daily_sales_report'),
    path('dashboard/download/monthly-sales/', views.download_monthly_sales_report, name='download_monthly_sales_report'),

    path('site-content/', views.site_content_list, name='site_content_list'),
    path('site-content/manage/', views.site_content_create_or_update, name='site_content_manage'),
    path('site-content/delete/', views.site_content_delete, name='site_content_delete'),
    path('send-reminder/<int:user_id>/<str:reminder_type>/', views.send_reminder_email, name='send_reminder_email'),
    path('send-reengagement-email/<int:user_id>/', views.send_reengagement_email, name='send_reengagement_email'),

    path('brands/', views.brand_list_view, name='brand_list'),
    path('brands/add/', views.add_brand_view, name='add_brand'),
    path('brands/edit/<int:pk>/', views.edit_brand_view, name='edit_brand'),
    path('brands/delete/<int:pk>/', views.delete_brand_view, name='delete_brand'),

              ]+ static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

