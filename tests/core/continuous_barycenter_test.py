# Copyright 2022 Apple
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Lint as: python3
"""Tests for Continuous barycenters."""

import jax
import jax.numpy as jnp
from absl.testing import absltest, parameterized

from ott.core import bar_problems, continuous_barycenter
from ott.geometry import costs


class Barycenter(parameterized.TestCase):

  def setUp(self):
    super().setUp()
    self.rng = jax.random.PRNGKey(0)
    self._dim = 4
    self._num_points = 113

  @parameterized.product(
      rank=[-1, 6],
      epsilon=[1e-1, 1e-2],
      jit=[True, False],
      init_random=[True, False]
  )
  def test_euclidean_barycenter(self, rank, epsilon, jit, init_random):
    rngs = jax.random.split(self.rng, 20)
    # Sample 2 point clouds, each of size 113, the first around [0,1]^4,
    # Second around [2,3]^4.
    y1 = jax.random.uniform(rngs[0], (self._num_points, self._dim))
    y2 = jax.random.uniform(rngs[1], (self._num_points, self._dim)) + 2
    # Merge them
    y = jnp.concatenate((y1, y2))

    # Define segments
    num_per_segment = jnp.array([33, 29, 24, 27, 27, 31, 30, 25])
    # Set weights for each segment that sum to 1.
    b = []
    for i in range(num_per_segment.shape[0]):
      c = jax.random.uniform(rngs[i], (num_per_segment[i],))
      b.append(c / jnp.sum(c))
    b = jnp.concatenate(b, axis=0)
    print(b.shape)
    # Set a barycenter problem with 8 measures, of irregular sizes.

    bar_prob = bar_problems.BarycenterProblem(
        y,
        b,
        num_per_segment=num_per_segment,
        num_segments=num_per_segment.shape[0],
        max_measure_size=jnp.max(num_per_segment) +
        3,  # +3 set with no purpose.
        epsilon=epsilon
    )

    # Define solver
    threshold = 1e-3
    solver = continuous_barycenter.WassersteinBarycenter(
        rank=rank, threshold=threshold, jit=jit
    )

    # Set barycenter size to 31.
    bar_size = 31

    # We consider either a random initialization, with points chosen
    # in [0,1]^4, or the default (init_random is False) where the
    # initialization consists in selecting randomly points in the y's.
    if init_random:
      # choose points randomly in area relevant to the problem.
      x_init = 3 * jax.random.uniform(rngs[-1], (bar_size, self._dim))
      out = solver(bar_prob, bar_size=bar_size, x_init=x_init)
    else:
      out = solver(bar_prob, bar_size=bar_size)

    # Check shape is as expected
    self.assertTrue(out.x.shape == (bar_size, self._dim))

    # Check convergence by looking at cost evolution.
    costs = out.costs
    costs = costs[costs > -1]
    self.assertTrue(jnp.isclose(costs[-2], costs[-1], rtol=threshold))

    # Check barycenter has all points roughly in [1,2]^4.
    # (this is because sampled points were equally set in either [0,1]^4
    # or [2,3]^4)
    self.assertTrue(jnp.all(out.x.ravel() < 2.3))
    self.assertTrue(jnp.all(out.x.ravel() > .7))

  @parameterized.product(
      lse_mode=[True, False], epsilon=[1e-1, 5e-1], jit=[True, False]
  )
  def test_bures_barycenter(self, lse_mode, epsilon, jit):
    num_measures = 2
    num_components = 2
    dimension = 2
    bar_size = 2
    barycentric_weights = jnp.asarray([0.5, 0.5])
    bures_cost = costs.Bures(dimension=dimension)

    means1 = jnp.array([[-1., 1.], [-1., -1.]])
    means2 = jnp.array([[1., 1.], [1., -1.]])
    sigma = 0.01
    covs1 = sigma * jnp.asarray([
        jnp.eye(dimension) for i in range(num_components)
    ])
    covs2 = sigma * jnp.asarray([
        jnp.eye(dimension) for i in range(num_components)
    ])

    y1 = bures_cost.means_and_covs_to_x(means1, covs1)
    y2 = bures_cost.means_and_covs_to_x(means2, covs2)

    b1 = b2 = jnp.ones(num_components) / num_components

    y = jnp.concatenate((y1, y2))
    b = jnp.concatenate((b1, b2))

    key = jax.random.PRNGKey(0)
    keys = jax.random.split(key, num=2)
    x_init_means = jax.random.uniform(keys[0], (bar_size, dimension))
    x_init_covs = jax.vmap(
        lambda a: a @ jnp.transpose(a), in_axes=0
    )(
        jax.random.uniform(keys[1], (bar_size, dimension, dimension))
    )

    x_init = bures_cost.means_and_covs_to_x(x_init_means, x_init_covs)

    bar_p = bar_problems.BarycenterProblem(
        y,
        b,
        weights=barycentric_weights,
        num_per_segment=jnp.asarray([num_components, num_components]),
        num_segments=num_measures,
        max_measure_size=num_components,
        cost_fn=bures_cost,
        epsilon=epsilon
    )

    solver = continuous_barycenter.WassersteinBarycenter(
        lse_mode=lse_mode, jit=jit
    )

    out = solver(bar_p, bar_size=bar_size, x_init=x_init)
    barycenter = out.x

    means_bary, covs_bary = bures_cost.x_to_means_and_covs(barycenter)

    self.assertTrue(
        jnp.logical_or(
            jnp.allclose(
                means_bary,
                jnp.array([[0., 1.], [0., -1.]]),
                rtol=1e-02,
                atol=1e-02
            ),
            jnp.allclose(
                means_bary,
                jnp.array([[0., -1.], [0., 1.]]),
                rtol=1e-02,
                atol=1e-02
            )
        )
    )

    self.assertTrue(
        jnp.allclose(
            covs_bary,
            jnp.array([sigma * jnp.eye(dimension) for i in range(bar_size)]),
            rtol=1e-05,
            atol=1e-05
        )
    )


if __name__ == '__main__':
  absltest.main()
