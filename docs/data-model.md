# Data Model

Minimum entities: users, sessions, login_attempts, resume_files, profile_versions, criteria_versions, schedules, app_settings, background_jobs, search_runs, vacancies, vacancy_sources, run_vacancies, vacancy_scores, vacancy_ui_state, cover_letters, source_health, audit_log. Scores and viewed state are user-scoped; historical scores reference profile and criteria versions; deleting a user deletes personal resume/profile/criteria/state while shared vacancy records may remain if referenced by other users.
