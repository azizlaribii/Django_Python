from django.test import TestCase
from django.urls import reverse

from .models import User


class NavigationTests(TestCase):
    def test_authenticated_navigation_displays_the_users_full_name(self):
        user = User.objects.create_user(
            username="leila-ben-salah",
            password="unit-test-password",
            first_name="Leila",
            last_name="Ben Salah",
            role=User.Role.DOCTEUR,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("home"))

        self.assertContains(response, "Leila Ben Salah")
        self.assertNotContains(response, "{{ user.get_full_name")
        self.assertNotContains(response, "octor %}")

    def test_admin_laboratory_menu_keeps_only_analysis_management_and_history(self):
        admin = User.objects.create_user(
            username="laboratory-admin",
            password="unit-test-password",
            role=User.Role.ADMIN,
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("admin_dashboard"))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertEqual(html.count('class="nav-mega-link"'), 2)
        for section in (
            "Gestion des analyses",
            "Historique et traçabilité",
        ):
            self.assertContains(response, section)
        self.assertContains(response, "Résumé de l’activité du laboratoire")
        self.assertNotContains(response, "Rapports et exports")
        self.assertNotContains(response, "Suivi du laboratoire")
        self.assertNotContains(response, "Paramètres du laboratoire</strong>")
        self.assertNotIn(reverse("laboratoire:prelevement_list"), html)
