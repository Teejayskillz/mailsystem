from django import forms


class LoginForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(
            attrs={"autocomplete": "username", "autofocus": True, "class": "form-control"}
        ),
    )
    password = forms.CharField(
        widget=forms.PasswordInput(
            attrs={"autocomplete": "current-password", "class": "form-control"}
        )
    )


class GenerateForm(forms.Form):
    label = forms.CharField(
        required=False,
        max_length=64,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Optional label (e.g. newsletter, trial)",
                "autocomplete": "off",
            }
        ),
    )
