-- Migration: Add market_offers table for farmer-vendor price bargaining
-- Run this after orders table exists

CREATE TABLE IF NOT EXISTS market_offers (
    id SERIAL PRIMARY KEY,
    farmer_inventory INTEGER REFERENCES farmer_inventory(id) ON DELETE CASCADE NOT NULL,
    vendor INTEGER REFERENCES users(id) ON DELETE CASCADE NOT NULL,
    farmer INTEGER REFERENCES users(id) ON DELETE CASCADE NOT NULL,
    vendor_offer_price FLOAT NOT NULL,
    farmer_counter_price FLOAT,
    quantity_kg FLOAT NOT NULL,
    message VARCHAR(255),
    status VARCHAR(20) NOT NULL,
    order_id INTEGER REFERENCES orders(id) ON DELETE SET NULL,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_market_offers_farmer ON market_offers(farmer);
CREATE INDEX IF NOT EXISTS idx_market_offers_vendor ON market_offers(vendor);
CREATE INDEX IF NOT EXISTS idx_market_offers_inventory ON market_offers(farmer_inventory);
CREATE INDEX IF NOT EXISTS idx_market_offers_status ON market_offers(status);
