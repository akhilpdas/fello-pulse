export function TierBadge({ tier }: { tier: string }) {
  return <span className={`tier tier-${tier}`}>{tier === "abstain" ? "low confidence" : tier}</span>;
}
