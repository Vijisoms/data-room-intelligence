# Azure Deployment Plan

> **Status:** Planning

Generated: 2026-10-15T03:38:28-05:00

---

## 1. Project Overview

**Goal:** Keep the existing Microsoft Foundry project and add a secure storage
relay that lets the local deterministic ingestion workflow publish canonical
artifacts and lets the Foundry Hosted Agent read those artifacts. The existing
artifact Storage account remains private-only.

**Path:** Add Components

**Resource group:** `rsg_af`

**Existing resources retained:**

- Foundry account `MF-for-Agents`
- Foundry project `proj-default`
- Storage account `drintvijiso404199`
- Private Blob container `data-room-intelligence`

---

## 2. Requirements

| Attribute | Value |
|-----------|-------|
| Classification | Development / internal pilot |
| Scale | Small; fewer than 1,000 users with low, bursty traffic |
| Budget | Cost-optimized; scale to zero where supported |
| Subscription | `ME-MngEnvMCAP404199-vijiso-1` (`b48d162c-1055-4e6d-81e4-4ae4bad1f903`) |
| Tenant | `dce80db1-1f53-4c3a-9aa6-98f5a78a959e` |
| Location | Sweden Central |
| Data residency | Keep application and data resources in Sweden Central |
| Authentication | Microsoft Entra ID through App Service Authentication (Easy Auth) |
| Secrets | No Storage keys, SAS tokens, or committed credentials |

### Policy Constraints

- Inherited `MCAPSGov Deny Policies`, `MCAPSGov Deploy and Modify Policies`,
  `MCAPSGov Audit Policies`, and `Azure Security Baseline` assignments are
  enforced.
- The existing Storage account's effective `publicNetworkAccess` is
  `Disabled`; attempted changes are reverted or blocked by policy.
- Shared-key access and public Blob access remain disabled.
- The design must use private endpoints, managed identity, and Azure RBAC.
- A policy what-if and deployment validation must run before deployment.

---

## 3. Components Detected

| Component | Type | Technology | Path |
|-----------|------|------------|------|
| Deterministic ingestion | Local workflow | Python 3.13, Microsoft Agent Framework, Excel COM, GeoPandas | `src/data_room_intelligence/` |
| Artifact publisher/reader | Library | Python, Azure Blob SDK | `src/data_room_intelligence/artifacts.py` |
| Cited Q&A agent | Foundry Hosted Agent | Python 3.13, Responses protocol | `hosted_agent/` |
| Relay API | New serverless API | Python Azure Functions v2 programming model | `relay/` |
| Relay infrastructure | New IaC | Bicep | `infra/` |

The Excel/GIS/PDF ingestion workflow remains local. Only normalized output
artifacts pass through the relay.

---

## 4. Recipe Selection

**Selected:** Bicep for the relay infrastructure, with the existing Foundry
`azure.yaml` retained for the Hosted Agent.

**Rationale:**

- The workspace already uses the Foundry-specific `microsoft.foundry` provider
  in `azure.yaml`; replacing it would disrupt the existing Hosted Agent path.
- Group-scoped Bicep cleanly adds networking, Functions, monitoring, private
  endpoints, RBAC, and authentication to the existing resource group.
- The relay deployment remains reproducible and can be validated with ARM
  what-if before execution.
- Foundry Hosted Agent deployment remains a separate `azd` operation after the
  user manually reauthenticates `azd` to the active tenant.

---

## 5. Architecture

**Stack:** Serverless

### Request Flow

1. The local deterministic pipeline generates canonical artifacts.
2. The local publisher obtains an Entra token with `DefaultAzureCredential`
   and uploads a bounded artifact run to the public HTTPS relay endpoint.
3. Easy Auth rejects anonymous or unapproved callers with HTTP 401/403.
4. The relay validates asset IDs, artifact names, content types, payload sizes,
   and checksums.
5. The relay's system-assigned managed identity writes through VNet integration
   and a Blob private endpoint to `drintvijiso404199`.
6. The relay commits `latest.json` only after every run artifact is stored.
7. The existing Foundry Hosted Agent obtains a managed-identity token and reads
   the latest manifest and named artifacts through the same relay.
8. The Hosted Agent answers only from deterministic canonical outputs and
   returns source citations and QA warnings.

### Network Layout

| Network | Address range | Purpose |
|---------|---------------|---------|
| `vnet-drint-relay` | `10.42.0.0/16` | Dedicated relay network |
| `snet-functions` | `10.42.0.0/26` | Flex Consumption outbound VNet integration; delegated to `Microsoft.App/environments` |
| `snet-private-endpoints` | `10.42.1.0/27` | Storage private endpoints; private endpoint network policies disabled |

Private DNS zones linked to the VNet:

- `privatelink.blob.core.windows.net`
- `privatelink.queue.core.windows.net`
- `privatelink.table.core.windows.net`

The relay retains public HTTPS ingress because the current Foundry project and
local workstation are not inside the VNet. Public ingress is not anonymous:
Easy Auth requires tokens from this tenant, approved client applications, and
approved identities.

### Service Mapping

| Component | Azure Service | SKU |
|-----------|---------------|-----|
| Relay API | Azure Functions | Flex Consumption `FC1`, Linux, Python 3.13, 2,048 MB, maximum 10 instances |
| Relay runtime state | Azure Storage | Standard GPv2, LRS, private-only |
| Canonical artifacts | Existing Azure Storage | `drintvijiso404199`, Standard LRS, private-only |
| Private data path | Azure Private Link | Blob endpoint for artifact storage; Blob/Queue/Table endpoints for Functions runtime storage |
| Authentication | App Service Authentication + Microsoft Entra application | Single tenant; 401 for unauthenticated API requests |
| Authorization to Blob | Azure RBAC | Relay identity receives `Storage Blob Data Contributor` on the artifact container scope |
| Monitoring | Application Insights | Workspace-based |
| Logs | Log Analytics workspace | Pay-as-you-go |

### Caller Allowlist

Easy Auth will require all three checks:

1. Token issuer is the active tenant.
2. Client application is either the parent Foundry resource managed identity
   application or the Azure CLI public client used by the local operator.
3. Token identity is either the parent Foundry resource principal or the
   explicitly approved local operator principal.

The relay API audience will use a stable tenant-qualified URI:
`api://dce80db1-1f53-4c3a-9aa6-98f5a78a959e/data-room-storage-relay`.

### Bounded Relay Contract

| Method and route | Purpose |
|------------------|---------|
| `POST /api/assets/{asset_id}/runs` | Publish one complete allowlisted artifact run |
| `GET /api/assets/{asset_id}/latest` | Return the latest manifest |
| `GET /api/assets/{asset_id}/artifacts/{artifact_name}` | Return one allowlisted artifact from the latest run |
| `GET /api/health` | Return relay readiness without exposing artifact data |

The API will not expose arbitrary Blob paths, account/container listing,
deletion, copy, or overwrite of a committed run. Asset IDs and artifact names
use explicit allowlists. Payload and per-artifact limits will be enforced.

### Security Decisions

- System-assigned managed identity for relay-to-Storage access.
- `DefaultAzureCredential` locally and `ManagedIdentityCredential` in Azure.
- HTTPS only, TLS 1.2 minimum, FTPS disabled.
- Storage public network access and shared-key access remain disabled.
- CORS disabled unless a browser client is later approved.
- Easy Auth returns 401 rather than browser redirects.
- Application Insights captures request, dependency, exception, and
  authentication diagnostics without recording artifact payloads.
- Key Vault is intentionally not provisioned because this design contains no
  application secrets. Adding an unused vault and private endpoint would
  increase cost and operational surface without improving security.

---

## 6. Provisioning Limit Checklist

Quota checks ran against Sweden Central in subscription
`b48d162c-1055-4e6d-81e4-4ae4bad1f903`.

| Resource Type | Number to Deploy | Total After Deployment | Limit/Quota | Notes |
|---------------|------------------|------------------------|-------------|-------|
| `Microsoft.Network/virtualNetworks` | 1 | 1 | 1,000 | `az quota`: `VirtualNetworks`; current usage 0 |
| `Microsoft.Network/privateEndpoints` | 4 | 4 | 65,536 | `az quota`: `PrivateEndpoints`; current usage 0 |
| VNet subnets | 2 | 2 | 3,000 per VNet | `az quota`: `SubnetsPerVirtualNetwork` |
| `Microsoft.Storage/storageAccounts` | 1 | 2 | 250 | `az quota`: `StorageAccounts`; current usage 1 |
| `Microsoft.Web/serverfarms` / Flex capacity | 1 | 1 | 10 | `az quota` for `Microsoft.Web`; current usage 0 |
| `Microsoft.Web/sites` | 1 | 1 | Covered by Microsoft.Web regional quota | Azure Resource Graph current usage 0 |
| `Microsoft.Network/privateDnsZones` | 3 | 3 | 1,000 per subscription | Azure service limit; current usage 0 in the target design |
| `Microsoft.OperationalInsights/workspaces` | 1 | 1 | No regional resource-count quota published | Quota provider returned no rows; Azure Resource Graph current usage 0 |
| `Microsoft.Insights/components` | 1 | 1 | No regional resource-count quota published | Azure Resource Graph current usage 0 |

**Status:** All planned resources are within available limits.

---

## 7. Execution Checklist

### Phase 1: Planning

- [x] Analyze workspace
- [x] Gather requirements
- [x] Confirm subscription and location with user
- [x] Inspect inherited policy assignments
- [x] Prepare resource inventory
- [x] Fetch quotas and validate capacity
- [x] Scan codebase
- [x] Select recipe
- [x] Plan architecture
- [ ] User approved this plan

### Phase 2: Preparation

- [ ] Load Azure Functions composition and infrastructure templates
- [ ] Create the Python relay project and bounded HTTP routes
- [ ] Add relay client transport to the local artifact publisher
- [ ] Replace direct Blob reads in the Hosted Agent with relay reads
- [ ] Generate Bicep for Functions, VNet, private endpoints, DNS, monitoring,
      identity, RBAC, Entra authentication, and policy-compliant Storage
- [ ] Add configuration to `.env.example`, hosted-agent environment, and
      `azure.yaml`
- [ ] Add unit tests for route validation, publishing, manifest atomicity, and
      relay clients
- [ ] Update README architecture and operating instructions
- [ ] Run local tests, lint/type checks, Bicep build, and ARM what-if validation
- [ ] Update status to `Ready for Validation`

### Phase 3: Validation and Deployment

- [ ] Invoke `azure-validate` and record validation proof
- [ ] Deploy relay infrastructure through the validated Bicep recipe
- [ ] Deploy relay code
- [ ] Verify private DNS resolves Storage to private IP from the Function
- [ ] Verify anonymous relay calls fail
- [ ] Verify local Entra-authenticated publish succeeds
- [ ] Manually reauthenticate `azd` to tenant
      `dce80db1-1f53-4c3a-9aa6-98f5a78a959e`
- [ ] Deploy/update the existing Foundry Hosted Agent
- [ ] Verify managed-identity relay read and cited Q&A
- [ ] Verify live RBAC assignments and monitoring
- [ ] Commit and push the completed changes to the private GitHub repository

---

## 8. Validation Proof

Pending implementation and the mandatory `azure-validate` phase. This section
must contain commands, timestamps, and results before deployment.

---

## 9. Rollback

- Keep the existing local output workflow operational throughout.
- Relay infrastructure is additive; no existing Foundry or Storage resource is
  replaced.
- If relay deployment fails, remove only the newly created relay resources
  after explicit user approval.
- Do not re-enable Storage public network access and do not introduce keys or
  SAS as a fallback.

