from django.contrib import admin

from .models import (
    AdoptionApplication,
    AdoptionContract,
    HomePhotoReport,
    Interview,
    Pet,
    Profile,
    SponsorshipPayment,
    VetCard,
    Volier,
    WalkingBooking,
)

admin.site.site_header = "Лапа помощи — администрирование"
admin.site.site_title = "Лапа помощи"
admin.site.index_title = "Управление приютом"


class VetCardInline(admin.StackedInline):
    model = VetCard
    extra = 0


@admin.register(Volier)
class VolierAdmin(admin.ModelAdmin):
    list_display = ("number", "sector", "capacity")
    list_filter = ("sector",)
    search_fields = ("number", "sector")


@admin.register(Pet)
class PetAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "species",
        "breed",
        "age",
        "gender",
        "status",
        "volier",
        "admission_date",
    )
    list_filter = ("species", "status", "gender", "volier")
    list_editable = ("status",)
    search_fields = ("name", "breed", "description")
    exclude = ("sponsors",)
    inlines = [VetCardInline]
    actions = ["make_available", "make_quarantine"]

    @admin.action(description="Отметить как «Доступен»")
    def make_available(self, request, queryset):
        queryset.update(status="available")

    @admin.action(description="Отметить как «На карантине»")
    def make_quarantine(self, request, queryset):
        queryset.update(status="quarantine")


@admin.register(VetCard)
class VetCardAdmin(admin.ModelAdmin):
    list_display = ("pet", "last_checkup")
    list_filter = ("last_checkup",)
    search_fields = ("pet__name", "diagnosis")


@admin.register(AdoptionApplication)
class AdoptionApplicationAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "pet", "status", "created_at")
    list_filter = ("status", "created_at")
    list_editable = ("status",)
    search_fields = ("user__username", "user__email", "pet__name")
    actions = ["approve", "reject"]

    @admin.action(description="Одобрить выбранные заявки")
    def approve(self, request, queryset):
        for application in queryset.filter(status="pending"):
            application.status = "approved"
            application.save()

    @admin.action(description="Отклонить выбранные заявки")
    def reject(self, request, queryset):
        queryset.filter(status="pending").update(status="rejected")


@admin.register(Interview)
class InterviewAdmin(admin.ModelAdmin):
    list_display = ("application", "curator", "scheduled_time", "passed")
    list_select_related = ("application__user", "application__pet", "curator")
    list_filter = ("passed", "scheduled_time")
    search_fields = ("application__user__username", "application__pet__name")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "curator":
            kwargs["queryset"] = db_field.related_model.objects.filter(is_staff=True)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(WalkingBooking)
class WalkingBookingAdmin(admin.ModelAdmin):
    list_display = ("pet", "volunteer", "date_time", "is_completed")
    list_filter = ("is_completed", "date_time")
    list_editable = ("is_completed",)
    search_fields = ("pet__name", "volunteer__username")
    actions = ["complete"]

    @admin.action(description="Отметить прогулки завершёнными")
    def complete(self, request, queryset):
        queryset.update(is_completed=True)


@admin.register(AdoptionContract)
class AdoptionContractAdmin(admin.ModelAdmin):
    list_display = ("id", "application", "signed_date", "terms_agreed")
    list_select_related = ("application__user", "application__pet")
    list_filter = ("signed_date", "terms_agreed")
    search_fields = ("application__user__username", "application__pet__name")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        obj.application.status = "completed"
        obj.application.save()
        obj.application.pet.status = "adopted"
        obj.application.pet.save()


@admin.register(SponsorshipPayment)
class SponsorshipPaymentAdmin(admin.ModelAdmin):
    list_display = ("sponsor", "pet", "amount", "payment_type", "payment_date")
    list_filter = ("payment_type", "payment_date", "pet")
    search_fields = ("sponsor__username", "pet__name")


@admin.register(HomePhotoReport)
class HomePhotoReportAdmin(admin.ModelAdmin):
    list_display = ("contract", "report_date", "comment")
    list_select_related = ("contract__application__user", "contract__application__pet")
    list_filter = ("report_date",)
    search_fields = ("comment", "contract__application__pet__name")


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "phone", "gender")
    list_filter = ("gender",)
    search_fields = ("user__username", "phone")
