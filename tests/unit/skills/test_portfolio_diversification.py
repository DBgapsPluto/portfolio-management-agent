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


def test_enb_perfectly_correlated_equal_weight_symmetric():
    # 등상관 + 등가중 + 등분산은 permutation symmetric → 최소-LINEAR-torsion 은
    # N 개의 균등-분산 비상관 factor (p_i = 1/N) 를 만들어 ENB = N (= 4) 이 된다.
    # ρ→1 이어도 마찬가지: 최소-비틀림은 PCA 와 달리 상관이 높아도 붕괴하지 않는다.
    # (이전 assert ≈1 은 buggy eigenvalue 분해가 만든 PCA-식 붕괴값이었음 — PCA 붕괴는
    #  아래 test_compute_enb_pca_perfectly_correlated_returns_one 가 별도로 검증.)
    sigma = _equal_corr_cov(4, rho=0.999999)
    enb = compute_enb(_equal_weights(sigma), sigma)
    assert enb == pytest.approx(4.0, abs=1e-6)


def test_enb_half_correlated_two_assets_symmetric():
    # 2 자산 corr 0.5 등가중 → permutation symmetric → p = [0.5, 0.5] → ENB = 2 (정확).
    # (이전 1.4<enb<1.8 은 buggy eigenvalue 분해값이었음.)
    sigma = _equal_corr_cov(2, rho=0.5)
    enb = compute_enb(_equal_weights(sigma), sigma)
    assert enb == pytest.approx(2.0, abs=1e-6)


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


def test_compute_enb_pca_method_works():
    """PCA method smoke — fallback path 가 정상 동작 (Phase 1 followup, Phase 2a Task 10)."""
    sigma = _equal_corr_cov(3, rho=0.3)
    enb_mt = compute_enb(_equal_weights(sigma), sigma, method="minimum_torsion")
    enb_pca = compute_enb(_equal_weights(sigma), sigma, method="pca")
    # ENB ∈ [1, n] 범위 (등상관·등가중 symmetric 이라 최소-비틀림은 정확히 n=3,
    #  float epsilon 허용)
    assert 1.0 <= enb_mt <= 3.0 + 1e-9, f"minimum_torsion ENB out of range: {enb_mt}"
    assert 1.0 <= enb_pca <= 3.0 + 1e-9, f"pca ENB out of range: {enb_pca}"


def test_compute_enb_pca_perfectly_correlated_returns_one():
    """PCA: 완전 상관 portfolio → ENB ≈ 1."""
    sigma = _equal_corr_cov(4, rho=0.999999)
    enb_pca = compute_enb(_equal_weights(sigma), sigma, method="pca")
    assert enb_pca == pytest.approx(1.0, abs=1e-2)


# ---------- minimum_torsion factor-variance correctness (eigenvalue-misuse bug fix) ----------
# Bug: factor_var = exposures² × eigh(Σ) (sorted eigenvalues) instead of × diag(Σ).
# 최소-비틀림 factor 의 분산은 diag(Σ) (T Σ Tᵀ = diag(diag Σ) 정의에서). 정렬된 eigenvalue
# 는 자산 index 와 순서·의미가 불일치 → 분산 분해가 깨지고 ENB 가 ~1 로 붕괴.
# 아래 테스트는 비균등 분산/블록 구조에서 버그를 노출 (균등 대각/균등상관 case 는 버그가
# 우연히 가려져 통과하므로 위 기존 테스트만으로는 회귀를 못 잡았음).


def _spd_cov(n: int, seed: int) -> tuple[np.ndarray, np.ndarray]:
    """랜덤 SPD Σ + 합 1 random weights 반환."""
    rng = np.random.default_rng(seed)
    A = rng.standard_normal((n, n))
    sigma = A @ A.T + np.eye(n) * 0.5
    w = rng.random(n)
    w = w / w.sum()
    return sigma, w


def test_minimum_torsion_variance_decomposition_is_exact():
    """분산 분해 항등식: Σ_i e_i²·diag(Σ)_i == w^T Σ w (정확).

    버그(×eigenvalue)면 이 합이 w^TΣw 와 불일치한다. 정의상 정확히 일치해야 함.
    """
    from tradingagents.skills.portfolio.diversification import minimum_torsion_matrix

    for seed in (1, 7, 123, 2026):
        sigma, w = _spd_cov(6, seed)
        T = minimum_torsion_matrix(sigma)
        exposures = np.linalg.solve(T.T, w)
        lhs = float(np.sum(exposures ** 2 * np.diag(sigma)))
        rhs = float(w @ sigma @ w)
        assert lhs == pytest.approx(rhs, rel=1e-9), f"seed={seed}: {lhs} != {rhs}"


def test_minimum_torsion_decomposition_sums_to_one():
    """반환 p_i 의 합 = 1 (분산 기여 비율)."""
    sigma, w = _spd_cov(6, seed=42)
    p = minimum_torsion_decomposition(w, sigma)
    assert p.sum() == pytest.approx(1.0, abs=1e-9)
    assert np.all(p >= 0.0)


def _two_block_cov(k: int = 4, rho: float = 0.95, vol: float = 0.02) -> pd.DataFrame:
    """두 개의 강하게(intra rho) 상관된 블록 (4+4). 최소-비틀림은 가장 균형잡힌
    탈상관이라 N 개 균등-분산 factor 를 찾아 ENB ≈ N 을 준다 (PCA 와 대비)."""
    nn = 2 * k
    corr = np.eye(nn)
    for i in range(k):
        for j in range(k):
            if i != j:
                corr[i, j] = rho
    for i in range(k, nn):
        for j in range(k, nn):
            if i != j:
                corr[i, j] = rho
    sigma = np.full((nn, nn), vol * vol) * corr
    tickers = [f"A{i:06d}" for i in range(nn)]
    return pd.DataFrame(sigma, index=tickers, columns=tickers)


def test_enb_two_block_diversified_high():
    """2-블록(4+4) 등가중 → minimum_torsion ENB ≈ N(=8), NOT ~1.

    버그(×eigenvalue)면 ENB≈2.45 로 붕괴. 정확한 분해는 8.0.
    """
    sigma = _two_block_cov(k=4, rho=0.95)
    n = len(sigma.index)
    enb = compute_enb(_equal_weights(sigma), sigma)
    assert enb > n * 0.7, f"ENB collapsed: {enb} (expected ~{n})"
    assert enb == pytest.approx(8.0, abs=1e-6)


def test_enb_unequal_vol_low_corr_high():
    """비균등 분산 + 저상관 N=8 등가중 → ENB ≈ N (분산 분해 정확).

    eigh 정렬 eigenvalue 와 diag(Σ) 가 값·순서 모두 달라 버그를 노출하는 case.
    """
    n = 8
    vols = np.array([0.01, 0.012, 0.015, 0.018, 0.022, 0.027, 0.033, 0.04])
    corr = np.eye(n) + 0.03 * (np.ones((n, n)) - np.eye(n))
    sig = np.outer(vols, vols) * corr
    sig = (sig + sig.T) / 2
    tickers = [f"A{i:06d}" for i in range(n)]
    sigma = pd.DataFrame(sig, index=tickers, columns=tickers)
    enb = compute_enb(_equal_weights(sigma), sigma)
    assert enb > n * 0.7, f"ENB too low: {enb}"


def test_enb_dominant_variance_asset_low():
    """한 자산이 분산을 압도 (vol 0.5 vs 0.02) → ENB ≈ 1 (집중)."""
    n = 4
    vols = np.array([0.5, 0.02, 0.02, 0.02])
    sig = np.outer(vols, vols) * np.eye(n)
    tickers = [f"A{i:06d}" for i in range(n)]
    sigma = pd.DataFrame(sig, index=tickers, columns=tickers)
    enb = compute_enb(_equal_weights(sigma), sigma)
    assert enb < 1.5, f"dominant-asset ENB should be near 1, got {enb}"
