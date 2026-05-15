import numpy as np


def greedy_max_coverage(
    access_matrix: np.ndarray,
    demand_weights: np.ndarray,
    k: int,
    threshold: float = 10.0,
) -> list[int]:
    '''
    Жадный алгоритм максимизации охвата.

    access_matrix[i, j] — время доступа от точки спроса i
    до кандидатной локации j.

    demand_weights[i] — вес спроса в точке i.

    Возвращает индексы выбранных кандидатов.
    '''
    n_demand, n_candidates = access_matrix.shape

    selected: list[int] = []
    covered = np.zeros(n_demand, dtype=bool)
    remaining = set(range(n_candidates))

    for _ in range(k):
        best_candidate = None
        best_gain = -1.0

        for candidate in remaining:
            new_covered = covered | (access_matrix[:, candidate] <= threshold)
            gain = demand_weights[new_covered & ~covered].sum()

            if gain > best_gain:
                best_gain = gain
                best_candidate = candidate

        if best_candidate is None:
            break

        selected.append(best_candidate)
        remaining.remove(best_candidate)
        covered = covered | (access_matrix[:, best_candidate] <= threshold)

    return selected


def greedy_min_mean_time(
    access_matrix: np.ndarray,
    demand_weights: np.ndarray,
    k: int,
) -> list[int]:
    '''
    Жадный алгоритм минимизации среднего времени доступа.
    '''
    n_demand, n_candidates = access_matrix.shape

    selected: list[int] = []
    remaining = set(range(n_candidates))
    current_best_times = np.full(n_demand, np.inf)

    for _ in range(k):
        best_candidate = None
        best_score = np.inf

        for candidate in remaining:
            candidate_times = np.minimum(
                current_best_times,
                access_matrix[:, candidate]
            )
            score = np.average(candidate_times, weights=demand_weights)

            if score < best_score:
                best_score = score
                best_candidate = candidate

        if best_candidate is None:
            break

        selected.append(best_candidate)
        remaining.remove(best_candidate)
        current_best_times = np.minimum(
            current_best_times,
            access_matrix[:, best_candidate]
        )

    return selected


def greedy_max_effective_demand(
    access_matrix: np.ndarray,
    demand_weights: np.ndarray,
    k: int,
    tau: float = 10.0,
) -> list[int]:
    '''
    Жадный алгоритм максимизации эффективного спроса.
    Используется функция полезности exp(-t / tau).
    '''
    n_demand, n_candidates = access_matrix.shape

    selected: list[int] = []
    remaining = set(range(n_candidates))
    current_best_times = np.full(n_demand, np.inf)

    for _ in range(k):
        best_candidate = None
        best_score = -np.inf

        for candidate in remaining:
            candidate_times = np.minimum(
                current_best_times,
                access_matrix[:, candidate]
            )
            utility = np.exp(-candidate_times / tau)
            score = np.average(utility, weights=demand_weights)

            if score > best_score:
                best_score = score
                best_candidate = candidate

        if best_candidate is None:
            break

        selected.append(best_candidate)
        remaining.remove(best_candidate)
        current_best_times = np.minimum(
            current_best_times,
            access_matrix[:, best_candidate]
        )

    return selected
