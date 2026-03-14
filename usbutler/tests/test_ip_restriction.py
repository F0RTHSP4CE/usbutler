"""Tests for IP/CIDR matching utility."""

from app.dependencies import _ip_in_cidrs


class TestIpInCidrs:
    def test_match_in_subnet(self):
        assert _ip_in_cidrs("192.168.1.50", "192.168.1.0/24") is True

    def test_no_match(self):
        assert _ip_in_cidrs("10.0.0.1", "192.168.1.0/24") is False

    def test_multiple_cidrs(self):
        assert _ip_in_cidrs("10.0.0.1", "192.168.1.0/24,10.0.0.0/8") is True

    def test_exact_host(self):
        assert _ip_in_cidrs("172.16.0.1", "172.16.0.1/32") is True
        assert _ip_in_cidrs("172.16.0.2", "172.16.0.1/32") is False

    def test_empty_cidrs(self):
        assert _ip_in_cidrs("1.2.3.4", "") is False

    def test_invalid_ip(self):
        assert _ip_in_cidrs("not-an-ip", "192.168.1.0/24") is False

    def test_invalid_cidr_skipped(self):
        assert _ip_in_cidrs("10.0.0.1", "bad-cidr,10.0.0.0/8") is True

    def test_whitespace_handling(self):
        assert _ip_in_cidrs("10.0.0.1", " 10.0.0.0/8 , 192.168.0.0/16 ") is True

    def test_trailing_comma(self):
        assert _ip_in_cidrs("10.0.0.1", "10.0.0.0/8,") is True
