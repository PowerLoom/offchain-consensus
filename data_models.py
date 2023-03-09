import time
from pydantic import BaseModel
from typing import Union, List, Optional
from enum import Enum


class RedisConfig(BaseModel):
    host: str
    port: int
    db: int
    password: Optional[str]


class PeerUUIDIncludedRequests(BaseModel):
    instanceID: str


class PeerRegistrationRequest(PeerUUIDIncludedRequests):
    projectID: str


class EpochBase(BaseModel):
    begin: int
    end: int


class SnapshotBase(PeerUUIDIncludedRequests):
    epoch: EpochBase
    projectID: str


class EpochStatusRequest(PeerUUIDIncludedRequests):
    projectID: str
    epochs: List[EpochBase]


class SnapshotSubmission(SnapshotBase):
    snapshotCID: str


class SubmissionSchedule(BaseModel):
    begin: int
    end: int


class SubmissionDataStoreEntry(BaseModel):
    snapshotCID: str
    submittedTS: int


class SubmissionAcceptanceStatus(str, Enum):
    accepted = 'ACCEPTED'
    finalized = 'FINALIZED'
    # if the peer never submitted yet comes around checking for status, trying to work around the system
    notsubmitted = 'NOTSUBMITTED'
    # if all peers have submitted their snapshots and 2/3 consensus has not been reached
    # if submission deadline has passed, all peers have not submitted and 2/3 not reached
    indeterminate = 'INDETERMINATE'


class SubmissionStatus(str, Enum):
    within_schedule = 'WITHIN_SCHEDULE'
    delayed = 'DELAYED'


class EpochConsensusStatus(str, Enum):
    consensus_achieved = 'CONSENSUS_ACHIEVED'
    no_consensus = 'NO_CONSENSUS'


class EpochStatus(str, Enum):
    in_progress = 'IN_PROGRESS'
    finalized = 'FINALIZED'


class SubmissionResponse(BaseModel):
    status: Union[SubmissionAcceptanceStatus, EpochConsensusStatus]
    delayedSubmission: bool
    finalizedSnapshotCID: Optional[str] = None


class ConsensusService(BaseModel):
    submission_window: int
    host: str
    port: str
    keys_ttl: int = 86400


class NodeConfig(BaseModel):
    url: str


class RPCConfig(BaseModel):
    nodes: List[NodeConfig]
    retry: int
    request_timeout: int


class EpochConfig(BaseModel):
    height: int
    head_offset: int
    block_time: int
    history_length: int


class ConsensusCriteria(BaseModel):
    min_snapshotter_count: int
    percentage: int


class ChainConfig(BaseModel):
    rpc: RPCConfig
    chain_id: int
    epoch: EpochConfig


class SettingsConf(BaseModel):
    consensus_service: ConsensusService
    consensus_criteria: ConsensusCriteria
    redis: RedisConfig
    test_redis: Optional[RedisConfig]
    chain: ChainConfig
    rate_limit: str
    ticker_begin_block: Optional[int]


# Data model for a list of snapshotters
class ProjectSpecificSnapshotters(BaseModel):
    projectId: str
    snapshotters: List[str]


class Epoch(BaseModel):
    sourcechainEndheight: int
    finalized: bool


# Data model for a list of epoch data
class EpochData(BaseModel):
    projectId: str
    epochs: List[Epoch]


# Data model for a submission
class Submission(BaseModel):
    snapshotterName: str
    snapshotCID: str
    submittedTS: int
    submissionStatus: SubmissionStatus


class Message(BaseModel):
    message: str


class EpochInfo(BaseModel):
    chainId: int
    epochStartBlockHeight: int
    epochEndBlockHeight: int


class EpochDataPage(BaseModel):
    total: int
    next_page: Optional[str]
    prev_page: Optional[str]
    data: EpochData


class EpochDetails(BaseModel):
    epochEndHeight: int
    releaseTime: int
    status: EpochStatus
    totalProjects: int
    projectsFinalized: int


class SnapshotterIssueSeverity(str, Enum):
    high = 'HIGH'
    medium = 'MEDIUM'
    low = 'LOW'
    cleared = 'CLEARED'


class SnapshotterIssue(BaseModel):
    instanceID: str
    namespace: Optional[str]
    severity: SnapshotterIssueSeverity
    issueType: str
    projectID: str
    serviceName: str
    epochs: Optional[List[int]]
    extra: Optional[dict]
    timeOfReporting: Optional[int]
    noOfEpochsBehind: Optional[int]


class SnapshotterAliasIssue(BaseModel):
    alias: str
    namespace: Optional[str]
    severity: SnapshotterIssueSeverity
    issueType: str
    projectID: str
    serviceName: str
    epochs: Optional[List[int]]
    extra: Optional[dict]
    timeOfReporting: Optional[int]
    noOfEpochsBehind: Optional[int]


class UserStatusEnum(str, Enum):
    active = 'active'
    inactive = 'inactive'


class SnapshotterMetadata(BaseModel):
    rate_limit: str
    active: UserStatusEnum
    callsCount: int = 0
    throttledCount: int = 0
    next_reset_at: int = int(time.time()) + 86400
    name: str
    email: str
    alias: str
    uuid: Optional[str] = None
