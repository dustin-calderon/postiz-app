#!/bin/sh
psql -U postiz postiz_db -c "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='Media' ORDER BY ordinal_position;"
