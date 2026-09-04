import type {
  KirinActionPayloads,
  KirinOperationEnvelope,
  KirinPlugin,
} from "../../sdk/plugin/kirin-plugin-sdk.mjs";

const evaluation = {
  target: "example.total",
  overrides: { "example.rate": "25%" },
} satisfies KirinActionPayloads["evaluate"];

const query = {
  kind: ["output", "analysis"],
  limit: 50,
} satisfies KirinActionPayloads["model.query"];

const proposal = {
  title: "Create a local Build",
  changes: [{
    kind: "create-from-template",
    template: "package:path:/example:entries/build.kirin",
    document_id: "example_build",
    bindings: { coefficient: "0.5" },
  }],
} satisfies KirinActionPayloads["proposal.submit"];

export type PluginSdkContractSmoke = {
  evaluation: typeof evaluation;
  query: typeof query;
  proposal: typeof proposal;
  evaluateResult: Awaited<ReturnType<KirinPlugin["operations"]["evaluate"]>>;
  proposalResult: Awaited<ReturnType<KirinPlugin["proposals"]["submit"]>>;
  storedPreference: Awaited<ReturnType<KirinPlugin["storage"]["get"]>>;
  presentedResult: Awaited<ReturnType<KirinPlugin["results"]["present"]>>;
  expectedEnvelope: KirinOperationEnvelope;
};
