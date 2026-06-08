# TODO.md — Instamart Expansion Plan

## Step 1: Backend — new Instamart module skeleton
- [ ] Create `backend/instamart/__init__.py`
- [ ] Create `backend/instamart/locations.py`
- [ ] Create `backend/instamart/scraper.py`
- [ ] Create `backend/instamart/routes.py`

## Step 2: Backend — schemas
- [ ] Update `backend/schemas/price.py` with Instamart request/response models

## Step 3: Backend — wiring in app + scheduler state
- [ ] Update `backend/main.py` to include Instamart router under `/price`
- [ ] Initialize `app.state.instamart_cron_status` in lifespan

## Step 4: Backend — shared scrape helpers + sheets + scheduler
- [ ] Add `INSTAMART_CITIES` and `format_instamart_row()` in `backend/utils/scrape_helpers.py`
- [ ] Add Instamart wide-format header writer + batch update functions in `backend/utils/google_sheets.py`
- [ ] Update `backend/scheduler.py` to implement full Instamart scrape + manual trigger + cron status updates

## Step 5: Frontend — types/constants/status
- [ ] Update `frontend/src/types/price-scraper.ts` to add `InstamartResult`, add `instamart` to `PageKey`, extend `CityScrapeConfig['brand']`
- [ ] Update `frontend/src/constants/cities.ts` with `INSTAMART_CITIES`
- [ ] Update `frontend/src/lib/status.ts` with `instamartStatusColor`

## Step 6: Frontend — decouple progress color coupling
- [ ] Update `frontend/src/components/quick-commerce/CityScrapePage.tsx` to use `config.progressColorClass` (remove blinkit coupling)
- [ ] Update `CityScrapeConfig` type to include `progressColorClass`

## Step 7: Frontend — routing/nav + Instamart page config
- [ ] Update `frontend/src/hooks/useHashPage.ts` to map `#/instamart`
- [ ] Update `frontend/src/components/layout/Header.tsx` to add Instamart nav item
- [ ] Update `frontend/src/app/page.tsx` to add `instamartConfig` and route to `CityScrapePage`

## Step 8: Frontend — scheduler UI
- [ ] Update `frontend/src/hooks/useSchedulerData.ts` to add Instamart cron polling + manual trigger handler
- [ ] Update `frontend/src/components/scheduler/SchedulerPage.tsx` to render Instamart `ManualTriggerCard`
- [ ] Update `frontend/src/components/scheduler/ManualTriggerCard.tsx` to include Instamart card config
- [ ] Update `frontend/src/components/scheduler/RunHistoryTable.tsx` to map `instamart_manual` badge

## Step 9: Verification
- [ ] Run `python -m py_compile` checks for new/modified backend files
- [ ] Run `npm run lint`
- [ ] Run `npm run build`

