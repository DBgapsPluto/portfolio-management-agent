"""Canonical ENB tests — minimum_torsion correctness on textbook cases."""
import numpy as np
import pandas as pd
import pytest

from tradingagents.skills.portfolio.diversification import (
    compute_enb,
    minimum_torsion_decomposition,
    minimum_torsion_matrix,
)


def _diag_cov(n: int, vol: float = 0.02) -> pd.DataFrame:
    tickers = [f"A{i:06d}" for i in range(n)]
    sigma = np.eye(n) * (vol ** 2)
    return pd.DataFrame(sigma, index=tickers, columns=tickers)


def _equal_corr_cov(n: int, rho: float, vol: float = 0.02) -> pd.DataFrame:
    tickers = [f"A{i:06d}" for i in range(n)]
    corr = np.full((n, n), rho)
    np.fill_diagonal(corr, 1.0)
    sigma = corr * (vol ** 2)
    return pd.DataFrame(sigma, index=tickers, columns=tickers)


def _equal_weights(sigma: pd.DataFrame) -> dict[str, float]:
    tickers = list(sigma.index)
    n = len(tickers)
    return {t: 1.0 / n for t in tickers}


def test_enb_single_asset():
    sigma = _diag_cov(1)
    enb = compute_enb({"A000000": 1.0}, sigma)
    assert enb == pytest.approx(1.0, abs=1e-9)


def test_enb_uncorrelated_equal_weight():
    for n in (2, 4, 8):
        sigma = _diag_cov(n)
        enb = compute_enb(_equal_weights(sigma), sigma)
        assert enb == pytest.approx(n, abs=1e-6), f"n={n}"


def test_enb_perfectly_correlated():
    sigma = _equal_corr_cov(4, rho=0.999999)
    enb = compute_enb(_equal_weights(sigma), sigma)
    assert enb == pytest.approx(1.0, abs=1e-2)


def test_enb_half_correlated_two_assets():
    sigma = _equal_corr_cov(2, rho=0.5)
    enb = compute_enb(_equal_weights(sigma), sigma)
    # 2 자산 corr 0.5 등가중 → 분석적 ENB ≈ 1.6 (Meucci 예시)
    assert 1.4 < enb < 1.8


def test_enb_scale_invariance():
    sigma_a = _equal_corr_cov(3, rho=0.3, vol=0.02)
    sigma_b = _equal_corr_cov(3, rho=0.3, vol=2.0)  # 100배
    enb_a = compute_enb(_equal_weights(sigma_a), sigma_a)
    enb_b = compute_enb(_equal_weights(sigma_b), sigma_b)
    assert enb_a == pytest.approx(enb_b, abs=1e-6)


def test_enb_non_psd_warning(caplog):
    # 음수 eigenvalue 인 가짜 cov — 클립 + 경고
    n = 3
    tickers = [f"A{i:06d}" for i in range(n)]
    M = np.array([[0.01, 0.02, 0.0], [0.02, 0.01, 0.0], [0.0, 0.0, 0.01]])
    sigma = pd.DataFrame(M, index=tickers, columns=tickers)  # not PSD
    with caplog.at_level("WARNING"):
        enb = compute_enb(_equal_weights(sigma), sigma)
    assert enb > 0  # 클립 후 계산 성공
    assert any("non-PSD" in r.message or "eigenvalue" in r.message.lower()
               for r in caplog.records)


def test_enb_zero_portfolio_variance():
    n = 3
    tickers = [f"A{i:06d}" for i in range(n)]
    sigma = pd.DataFrame(np.eye(n) * 1e-20, index=tickers, columns=tickers)
    enb = compute_enb(_equal_weights(sigma), sigma)
    # equal split → ENB = n
    assert enb == pytest.approx(n, abs=1e-6)


def test_minimum_torsion_matrix_decorrelates():
    sigma = _equal_corr_cov(4, rho=0.4).values
    T = minimum_torsion_matrix(sigma)
    transformed = T @ sigma @ T.T
    expected_diag = np.diag(np.diag(sigma))
    # off-diagonal 가 거의 0 (numerical 1e-9)
    off_diag = transformed - np.diag(np.diag(transformed))
    assert np.max(np.abs(off_diag)) < 1e-9
    # 분산은 보존 (diag(diag(Σ)) 와 동일)
    assert np.allclose(np.diag(transformed), np.diag(expected_diag), atol=1e-9)
