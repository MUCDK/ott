# Copyright OTT-JAX
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
import functools
from typing import Literal, Optional

import pytest

import jax
import jax.numpy as jnp
import jax.tree_util as jtu

import optax

from ott.neural.flow_models import flows, genot, models, utils


def data_match_fn(
    src_lin: Optional[jnp.ndarray], tgt_lin: Optional[jnp.ndarray],
    src_quad: Optional[jnp.ndarray], tgt_quad: Optional[jnp.ndarray], *,
    typ: Literal["lin", "quad", "fused"]
) -> jnp.ndarray:
  if typ == "lin":
    return utils.match_linear(x=src_lin, y=tgt_lin)
  if typ == "quad":
    return utils.match_quadratic(xx=src_quad, yy=tgt_quad)
  if typ == "fused":
    return utils.match_quadratic(xx=src_quad, yy=tgt_quad, x=src_lin, y=tgt_lin)
  raise NotImplementedError(f"Unknown type: {typ}.")


class TestGENOT:

  @pytest.mark.parametrize(
      "dl", [
          "lin_dl", "quad_dl", "fused_dl", "lin_cond_dl", "quad_cond_dl",
          "fused_cond_dl"
      ]
  )
  def test_genot(self, rng: jax.Array, dl: str, request):
    rng_init, rng_call, rng_data = jax.random.split(rng, 3)
    problem_type = dl.split("_")[0]
    dl = request.getfixturevalue(dl)

    src_dim = dl.lin_dim + dl.quad_src_dim
    tgt_dim = dl.lin_dim + dl.quad_tgt_dim
    cond_dim = dl.cond_dim

    vf = models.VelocityField(
        hidden_dims=[7, 7, 7],
        output_dims=[15, tgt_dim],
        condition_dims=None if cond_dim is None else [1, 3, 2],
    )
    model = genot.GENOT(
        vf,
        flow=flows.ConstantNoiseFlow(0.0),
        data_match_fn=functools.partial(data_match_fn, typ=problem_type),
        source_dim=src_dim,
        target_dim=tgt_dim,
        condition_dim=cond_dim,
        rng=rng_init,
        optimizer=optax.adam(learning_rate=1e-4),
    )

    _logs = model(dl.loader, n_iters=3, rng=rng_call)

    batch = next(iter(dl.loader))
    batch = jtu.tree_map(jnp.asarray, batch)
    src_cond = batch.get("src_condition")
    batch_size = 4 if src_cond is None else src_cond.shape[0]
    src = jax.random.normal(rng_data, (batch_size, src_dim))

    res = model.transport(src, condition=src_cond)

    assert jnp.sum(jnp.isnan(res)) == 0
    assert res.shape[-1] == tgt_dim
