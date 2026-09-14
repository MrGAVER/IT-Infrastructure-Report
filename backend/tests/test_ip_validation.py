import pytest
from fastapi import HTTPException

from app.services.validation import validate_ipv4_field, validate_prefix_length_field


class TestValidateIpv4Field:
    @pytest.mark.parametrize("value", [None, "", "10.0.0.1", "0.0.0.0", "255.255.255.255", "192.168.1.1"])
    def test_accepts_empty_and_valid_addresses(self, value):
        validate_ipv4_field(value, "IP")  # не должно бросить исключение

    @pytest.mark.parametrize(
        "value",
        [
            "не IP-адрес",
            "999.1.1.1",
            "1.2.3",
            "1.2.3.4.5",
            "01.0.0.1",  # ведущие нули — как и на фронтенде, запрещены
            "10.0.0.1/24",  # CIDR-нотация — отдельное поле prefix_length, не часть адреса
            "'; DROP TABLE devices; --",
        ],
    )
    def test_rejects_malformed_addresses(self, value):
        with pytest.raises(HTTPException) as exc_info:
            validate_ipv4_field(value, "IP-адрес интерфейса")
        assert exc_info.value.status_code == 422
        assert "IP-адрес интерфейса" in exc_info.value.detail

    def test_rejects_non_string_value(self):
        with pytest.raises(HTTPException):
            validate_ipv4_field(["10.0.0.1"], "IP")


class TestValidatePrefixLengthField:
    @pytest.mark.parametrize("value", [None, "", 0, 24, 32, "24", "0", "32"])
    def test_accepts_empty_and_valid_values(self, value):
        validate_prefix_length_field(value, "Префикс")  # не должно бросить исключение

    @pytest.mark.parametrize("value", [-1, 33, "33", "-1", "не число", "24.5", []])
    def test_rejects_out_of_range_or_malformed_values(self, value):
        with pytest.raises(HTTPException) as exc_info:
            validate_prefix_length_field(value, "Префикс IP-адреса интерфейса")
        assert exc_info.value.status_code == 422
        assert "Префикс IP-адреса интерфейса" in exc_info.value.detail
