function fallbackActions(plan) {
  return (plan.framing || [])
    .filter((item) => Number(item.deficit || 0) > 0)
    .map((item) => ({ ...item, suggested_shots: [] }))
    .sort((left, right) => {
      const missingOrder = Number(right.state === 'missing') - Number(left.state === 'missing');
      return missingOrder || right.deficit - left.deficit
        || String(left.framing).localeCompare(String(right.framing));
    });
}

export function coverageResolution(plan = {}) {
  const summary = plan.summary || {};
  const actions = plan.primary_actions?.length ? plan.primary_actions : fallbackActions(plan);
  const unresolved = Number(summary.unresolved_targets
    ?? (Number(summary.gaps || 0) + Number(summary.dimension_gaps || 0)));
  return {
    actions,
    unresolved,
    acknowledged: Boolean(plan.acknowledged),
    requiresAttention: Boolean(plan.requires_attention ?? unresolved > 0),
  };
}
