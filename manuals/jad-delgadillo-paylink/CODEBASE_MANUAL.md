# Codebase Manual

Generated at: 2026-02-17 23:42:10Z

## Project
- Name: `jad-delgadillo-paylink`
- Tech stack: Node.js, TypeScript
- Analyzer scope: file tree (depth <= 3), key entrypoints, Python AST symbols

## File Map (Preview)
- `apps/web/.eslintrc.js`
- `apps/web/app/layout.tsx`
- `apps/web/app/page.tsx`
- `apps/web/app/providers.tsx`
- `apps/web/components/background-beams-demo.tsx`
- `apps/web/components/copy-button.tsx`
- `apps/web/components/mobile-bottom-drawer.tsx`
- `apps/web/components/mobile-create-menu.tsx`
- `apps/web/components/mobile-dashboard-nav.tsx`
- `apps/web/components/mobile-page-title.tsx`
- `apps/web/components/preview-button.tsx`
- `apps/web/components/quick-pay-form.tsx`
- `apps/web/components/status-badge.tsx`
- `apps/web/components/stripe-connect-banner.tsx`
- `apps/web/components/stripe-connect-gate.tsx`
- `apps/web/components/stripe-connect-onboarding.tsx`
- `apps/web/components/usage-badge.tsx`
- `apps/web/lib/convex-demo.ts`
- `apps/web/lib/stripe-actions.ts`
- `apps/web/lib/utils.ts`
- `apps/web/middleware.ts`
- `apps/web/tailwind.config.ts`
- `packages/ai/src/index.ts`
- `packages/ai/src/openai.ts`
- `packages/ai/src/provider.ts`
- `packages/contract-kit/src/hash.ts`
- `packages/contract-kit/src/index.ts`
- `packages/contract-kit/src/prompts.ts`
- `packages/contract-kit/src/schema.ts`
- `packages/convex/convex/clients.ts`
- `packages/convex/convex/contractEvents.ts`
- `packages/convex/convex/files.ts`
- `packages/convex/convex/paymentTerminals.ts`
- `packages/convex/convex/payments.ts`
- `packages/convex/convex/productOrders.ts`
- `packages/convex/convex/products.ts`
- `packages/convex/convex/quickPays.ts`
- `packages/convex/convex/schema.ts`
- `packages/convex/convex/signatures.ts`
- `packages/convex/convex/stripeEvents.ts`
- `packages/convex/convex/templates.ts`
- `packages/convex/convex/terminalPayments.ts`
- `packages/convex/convex/users.ts`
- `packages/convex/http/stripeWebhook.ts`
- `packages/convex/src/index.ts`
- `packages/domain/src/contractState.ts`
- `packages/domain/src/index.ts`
- `packages/domain/src/templates.ts`
- `packages/icons/src/icon.tsx`
- `packages/icons/src/index.ts`
- `packages/pdf/src/draft.tsx`
- `packages/pdf/src/index.ts`
- `packages/pdf/src/stamp.ts`
- `packages/ui/src/button.tsx`
- `packages/ui/src/card.tsx`
- `packages/ui/src/checkbox.tsx`
- `packages/ui/src/copy-button.tsx`
- `packages/ui/src/dialog.tsx`
- `packages/ui/src/icons.ts`
- `packages/ui/src/index.ts`
- `packages/ui/src/input.tsx`
- `packages/ui/src/label.tsx`
- `packages/ui/src/separator.tsx`
- `packages/ui/src/tabs.tsx`
- `packages/ui/src/textarea.tsx`
- `packages/ui/src/toast.tsx`
- `packages/ui/src/tooltip.tsx`
- `packages/ui/src/utils.ts`

## Key Symbols
No key symbols extracted.

## Onboarding Notes
1. Start with `services/cli/main.py` to understand developer workflow.
2. Review `services/ingest` for indexing pipeline behavior.
3. Review `services/api` for runtime query behavior and response contract.
4. Review `services/core` for provider, config, and database abstractions.
