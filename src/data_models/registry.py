"""Import every model so SQLAlchemy can resolve string relationships and Alembic sees all tables."""
from src.data_models.users_model import Users  # noqa: F401
from src.data_models.roles_model import Roles  # noqa: F401
from src.data_models.permissions_model import Permissions  # noqa: F401
from src.data_models.role_permissions import RolePermissions  # noqa: F401
from src.data_models.miscellaneous_model import Miscellaneous_Data  # noqa: F401
from src.data_models.states_model import States  # noqa: F401
from src.data_models.districts_model import Districts  # noqa: F401
from src.data_models.catalog_model import ProduceCategories, Units, QualityStandards  # noqa: F401
from src.data_models.crops_model import Crops  # noqa: F401
from src.data_models.soil_model import Soil  # noqa: F401
from src.data_models.fertilizers_model import Fertilizers  # noqa: F401
from src.data_models.profiles_model import FarmerProfiles, VendorProfiles, VerificationRequests  # noqa: F401
from src.data_models.farmer_inventory_model import FarmerInventory  # noqa: F401
from src.data_models.listing_extras_model import (  # noqa: F401
    ListingImages, ListingPriceTiers, ListingCertifications, SavedListings,
    InventoryReservations, InventoryMovements, HarvestPlans,
)
from src.data_models.negotiation_model import Negotiations, Offers  # noqa: F401
from src.data_models.market_offers_model import MarketOffers  # noqa: F401
from src.data_models.orders_model import Orders, OrderStatusHistory, OrderAdjustments, Invoices  # noqa: F401
from src.data_models.transactions_model import Transactions, Refunds, Settlements, WebhookEvents  # noqa: F401
from src.data_models.logistics_model import Shipments  # noqa: F401
from src.data_models.notifications_model import Notifications  # noqa: F401
from src.data_models.messages_model import Messages  # noqa: F401
from src.data_models.reviews_model import Reviews  # noqa: F401
from src.data_models.buy_requests_model import BuyRequests, BuyRequestInvites, BuyRequestResponses  # noqa: F401
from src.data_models.favourites_model import FavouriteFarmers  # noqa: F401
from src.data_models.crop_alerts_model import CropAlerts  # noqa: F401
from src.data_models.farm_expenses_model import FarmExpenses  # noqa: F401
from src.data_models.disputes_model import Disputes, DisputeMessages  # noqa: F401
from src.data_models.platform_model import (  # noqa: F401
    PlatformSettings, PlatformSettingsHistory, AuditLogs, IdempotencyKeys, StoredFiles, UserSessions,
    DeviceTokens, OtpCodes, Reports, UserBlocks, AccountAppeals, Announcements, SupportTickets,
    SupportTicketMessages, NotificationPreferences, NotificationDeliveries, RecurringOrders,
)
from src.data_models.agents_model import (  # noqa: F401
    AgentWorkflowRuns, AgentWorkflowEvents, AgentApprovalRequests, AgentToolCalls, AgentModelCalls,
    ListingEmbeddings, DisputeInvestigationReports,
)
