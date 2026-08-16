"""Submission envelope for `POST /invoice` (RC_TICS §7).

The endpoint takes a *list* of these, one per invoice.
"""

from pydantic import BaseModel, ConfigDict

__all__ = ["Packet", "PacketHeader"]


class PacketHeader(BaseModel):
    """`requestTraceId` is the client-generated uid used later for inquiry."""

    model_config = ConfigDict(populate_by_name=True)

    requestTraceId: str
    fiscalId: str  # شناسه حافظه مالیاتی (memoryId)


class Packet(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    payload: str  # compact JWE of the signed invoice
    header: PacketHeader
