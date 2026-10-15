from __future__ import annotations

import os

from azure.core.credentials import TokenCredential
from azure.identity import AzureCliCredential, DefaultAzureCredential


def azure_credential() -> TokenCredential:
    """Return the keyless Azure credential for Foundry, Document Intelligence and Blob.

    Set AZURE_CLI_SUBSCRIPTION locally when the Azure CLI default tenant differs from
    the tenant that owns the resources. Leave it unset in Azure so managed identity
    is used through DefaultAzureCredential.
    """
    subscription = os.environ.get("AZURE_CLI_SUBSCRIPTION", "").strip()
    if subscription:
        return AzureCliCredential(subscription=subscription)
    return DefaultAzureCredential()
