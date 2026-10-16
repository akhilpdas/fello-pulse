export interface NavItem { label: string; to: string; operatorOnly: boolean }

const ALL: NavItem[] = [
  { label: "Queue", to: "/", operatorOnly: false },
  { label: "Low confidence", to: "/low-confidence", operatorOnly: false },
  { label: "Drafts", to: "/drafts", operatorOnly: false },
  { label: "Run log", to: "/runs", operatorOnly: false },
  { label: "Admin", to: "/admin", operatorOnly: true },
];

/** The pages a role may see. Hiding a link is courtesy; the server refuses the calls regardless (FR-004). */
export const navFor = (role: "csm" | "operator"): NavItem[] => ALL.filter((n) => role === "operator" || !n.operatorOnly);
