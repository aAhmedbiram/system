-- Database Indexes Migration Script
-- This script adds indexes to improve query performance
-- Run this script on your database to optimize frequently queried columns

-- Indexes for members table (most frequently queried)
CREATE INDEX IF NOT EXISTS idx_members_email ON members(email);
CREATE INDEX IF NOT EXISTS idx_members_phone ON members(phone);
CREATE INDEX IF NOT EXISTS idx_members_starting_date ON members(starting_date);
CREATE INDEX IF NOT EXISTS idx_members_actual_starting_date ON members(actual_starting_date);
CREATE INDEX IF NOT EXISTS idx_members_end_date ON members(end_date);
CREATE INDEX IF NOT EXISTS idx_members_membership_status ON members(membership_status);
CREATE INDEX IF NOT EXISTS idx_members_name ON members(name);

-- Indexes for attendance table
CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(attendance_date);
CREATE INDEX IF NOT EXISTS idx_attendance_member_id ON attendance(member_id);
CREATE INDEX IF NOT EXISTS idx_attendance_num ON attendance(num DESC);

-- Indexes for users table
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_is_approved ON users(is_approved);

-- Indexes for pending_member_edits table
CREATE INDEX IF NOT EXISTS idx_pending_edits_status ON pending_member_edits(status);
CREATE INDEX IF NOT EXISTS idx_pending_edits_member_id ON pending_member_edits(member_id);
CREATE INDEX IF NOT EXISTS idx_pending_edits_created_at ON pending_member_edits(created_at DESC);

-- Indexes for invoices table
CREATE INDEX IF NOT EXISTS idx_invoices_member_id ON invoices(member_id);
CREATE INDEX IF NOT EXISTS idx_invoices_invoice_date ON invoices(invoice_date DESC);
CREATE INDEX IF NOT EXISTS idx_invoices_invoice_number ON invoices(invoice_number);

-- Indexes for renewal_logs table
CREATE INDEX IF NOT EXISTS idx_renewal_logs_member_id ON renewal_logs(member_id);
CREATE INDEX IF NOT EXISTS idx_renewal_logs_renewal_date ON renewal_logs(renewal_date DESC);

-- Indexes for supplements table
CREATE INDEX IF NOT EXISTS idx_supplements_name ON supplements(name);

-- Indexes for supplement_sales table
CREATE INDEX IF NOT EXISTS idx_supplement_sales_supplement_id ON supplement_sales(supplement_id);
CREATE INDEX IF NOT EXISTS idx_supplement_sales_sale_date ON supplement_sales(sale_date DESC);

-- Indexes for staff table
CREATE INDEX IF NOT EXISTS idx_staff_name ON staff(name);

-- Indexes for staff_purchases table
CREATE INDEX IF NOT EXISTS idx_staff_purchases_staff_id ON staff_purchases(staff_id);
CREATE INDEX IF NOT EXISTS idx_staff_purchases_purchase_date ON staff_purchases(purchase_date DESC);

-- Composite indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_members_status_date ON members(membership_status, end_date);
CREATE INDEX IF NOT EXISTS idx_attendance_member_date ON attendance(member_id, attendance_date DESC);

-- Note: After creating indexes, you may want to run ANALYZE to update statistics
-- ANALYZE members;
-- ANALYZE attendance;
-- ANALYZE users;

