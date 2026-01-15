/**
 * Organization Switcher (shared)
 *
 * Following:
 * - behavior_validate_accessibility (Student)
 */

import { memo, useState } from 'react';
import type { Organization } from '../api/dashboard';
import './OrgSwitcher.css';

interface OrgSwitcherProps {
  organizations: Organization[];
  currentOrgId: string | null;
  onSelect: (orgId: string | null) => void;
}

const ChevronDownIcon = () => (
  <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
    <path
      d="M3 4.5L6 7.5L9 4.5"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const OrgSwitcher = memo(function OrgSwitcher({
  organizations,
  currentOrgId,
  onSelect,
}: OrgSwitcherProps) {
  const [isOpen, setIsOpen] = useState(false);
  const currentOrg = organizations.find((o) => o.id === currentOrgId);
  const currentLabel = currentOrg?.name ?? 'Personal workspace';

  return (
    <div className="org-switcher">
      <button
        type="button"
        className="org-switcher-trigger pressable"
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        aria-haspopup="menu"
        data-haptic="light"
      >
        <span className="org-switcher-label" title={currentLabel}>{currentLabel}</span>
        <ChevronDownIcon />
      </button>
      {isOpen && (
        <div className="org-switcher-dropdown animate-scale-in" role="menu" aria-label="Organizations">
          <button
            type="button"
            role="menuitem"
            className={`org-switcher-option ${!currentOrgId ? 'active' : ''}`}
            onClick={() => {
              onSelect(null);
              setIsOpen(false);
            }}
          >
            Personal workspace
          </button>
          {organizations.map((org) => (
            <button
              type="button"
              role="menuitem"
              key={org.id}
              className={`org-switcher-option ${currentOrgId === org.id ? 'active' : ''}`}
              onClick={() => {
                onSelect(org.id);
                setIsOpen(false);
              }}
            >
              {org.name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
});
