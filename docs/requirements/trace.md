# Requirements and the tests that show them

Every sentence of a requirement either promises something observable or explains. A promise nobody
shows is a decision recorded but never built. This file ties each sentence of a traced section to
what shows it, and `tests/test_requirements_trace.py` splits each traced section into sentences
(and table rows) the way this file does, and fails when a sentence has no row, a row no longer
matches its sentence, or a row names a test or an issue that isn't there
([`../process/testing.md`](../process/testing.md), "Principles").

A section joins when its code is built, with the slice that builds it (`DEVELOP.md`), as a
`## N. Title` heading here and a row per sentence under it; an item built before the rest of its
section joins alone, as `## N.M. Title`, with the items under it. Every section of the first
release is here by that release.

**Shown by** names, comma-separated:

- a test function (`test_…`, found in `tests/`);
- `tier 3: ` and the check a person makes, when only a person can show it (testing.md, "Tiers");
- `later: #n`, the issue the sentence waits on: a `future` issue, or the issue of the first-release
  slice that finishes it (`DEVELOP.md`), never the slice being built or one before it;
- `statement`: it explains, names a file or a limit, and promises nothing a test could show.

**Sentence starts** is the sentence's opening words, with Markdown emphasis and backticks dropped.
A table row is traced whole, its cells as written.

## 2.1. The music root

| Item | Sentence starts | Shown by |
|---|---|---|
| R2.1 | MusiKata's library is one folder and everything under it | test_a_scan_fills_the_index_and_a_second_reads_nothing, test_the_walk_skips_hidden_ignored_and_settings_folders_and_the_roots_own |
| R2.1 | On the first start (mockup X01-first-run) the user drops a folder onto the window | test_a_folder_dropped_is_the_root_and_the_first_of_several, test_a_drop_that_holds_no_folder_says_it_wants_one, test_the_folder_dialogs_choice_is_the_root, test_use_music_makes_the_music_folder_when_it_isnt_there, test_a_music_folder_that_cant_be_made_says_why, test_the_music_folder_offered_is_the_platforms_shown_from_the_home, test_the_first_start_asks_and_the_folder_chosen_becomes_the_configured_root, test_a_whole_first_run_with_nothing_configured_asks_for_the_root, test_the_first_starts_window_loads_with_its_text_in_its_boxes, test_a_first_start_tours_its_window_alone, tier 3: on each platform Choose folder… opens the platform's folder dialog and a folder dragged from the file manager onto the first start's window becomes the root |
| R2.1 | That folder is the configured root, changed in Settings (R13.2) | test_the_first_start_asks_and_the_folder_chosen_becomes_the_configured_root, test_choosing_a_root_writes_a_file_valid_under_its_schema_with_a_new_computer_id, test_choosing_a_root_keeps_what_it_doesnt_know_and_the_computers_id, test_the_run_opens_root_given_else_the_configured_one_else_asks_for_one, test_choose_another_folder_opens_it_in_the_windows_place_and_keeps_it, later: #26 |
| R2.1.2 | A root for one run | test_the_run_opens_root_given_else_the_configured_one_else_asks_for_one, test_a_root_given_for_the_run_is_named_in_the_title_and_never_kept |
| R2.1.2 | The window's title then names the root | test_the_title_names_a_root_given_for_the_run_only, test_a_root_given_for_the_run_is_named_in_the_title_and_never_kept |
| R2.1.1 | The root's card at the bottom of the sidebar shows its path | test_the_library_as_qml_reads_it, test_sizes_counts_and_the_cards_line, test_the_card_is_green_when_up_to_date_and_amber_naming_what_couldnt_be_read, test_the_dot_turns_while_the_root_is_scanned, test_the_dot_and_its_tooltip, later: #26 |

## 2.3. Scanning

| Item | Sentence starts | Shown by |
|---|---|---|
| R2.3 | On start, and when asked (⋮ › Rescan library), MusiKata walks the root | test_a_whole_run_scans_the_root_and_tours_it, test_the_sort_menu_orders_albums_and_the_more_menu_rescans |
| R2.3 | It reads a file's tags only when its size or modification time changed since the last scan | test_the_plan_reads_only_what_changed_or_is_new_and_lists_what_went, test_a_scan_fills_the_index_and_a_second_reads_nothing |
| R2.3 | A first scan shows its progress in the root's card and fills the views as it goes | test_a_scan_reports_progress_then_fills_the_list_and_the_card, test_a_first_scan_fills_the_views_as_it_goes |
| R2.3.1 | Hidden files and folders | test_the_walk_skips_hidden_ignored_and_settings_folders_and_the_roots_own, test_the_hidden_attribute_is_windows_hidden_flag, test_what_puts_a_folder_outside_the_library_now, tier 3: a folder given the hidden attribute in Windows' Explorer leaves the library at the next scan |
| R2.3.1 | The root's .musikata folder is never part of the library | test_the_walk_skips_hidden_ignored_and_settings_folders_and_the_roots_own |
| R2.3.2 | Symbolic links (Linux, macOS) and junctions (Windows) inside the root are followed like folders | test_links_are_followed_and_one_leading_back_is_skipped_and_logged, tier 3: a folder on another drive joined by a Windows junction is in the library |
| R2.3.2 | A link leading back to a folder already walked is skipped, and the log says so | test_links_are_followed_and_one_leading_back_is_skipped_and_logged, test_a_link_new_in_a_named_folder_leading_back_to_a_known_one_is_skipped |

## 2.4. Watching

| Item | Sentence starts | Shown by |
|---|---|---|
| R2.4 | While MusiKata runs, files added, changed, moved or removed under the root | test_files_added_changed_moved_and_removed_under_the_root_appear_while_it_runs, test_a_watched_change_rescans_its_folder_only_and_the_list_keeps_its_place, test_a_change_made_while_the_first_scan_goes_on_is_rescanned_after_it, test_a_folder_the_walk_reaches_is_watched_and_gathered_if_it_changed_since, test_one_scan_at_a_time_what_comes_meanwhile_waits_for_the_scan_to_end, test_a_list_keeps_its_place_and_its_search_when_a_scan_changes_its_rows, test_changes_are_gathered_for_a_second_from_the_first_then_due_together, test_a_change_in_a_watched_folder_is_gathered_and_ready_when_due, test_a_file_read_while_it_may_still_be_written_has_its_folder_looked_at_again, test_a_partial_scan_reads_only_the_folders_named_passing_by_the_known_ones_under_them, test_a_folder_new_under_a_named_one_is_walked_whole_and_one_gone_takes_its_rows, test_a_named_folder_ignored_hidden_or_gone_takes_its_rows_and_its_folders_with_it, test_a_move_into_a_named_folder_from_one_not_named_keeps_its_row, test_a_copy_then_its_original_removed_is_a_move_whichever_folder_is_scanned_first, test_a_write_musikata_made_itself_isnt_read_again_by_the_rescan_its_change_starts, test_a_file_saved_takes_its_row_from_the_write_and_the_rescan_its_change_starts_reads_nothing, test_a_write_musikata_made_is_expected_by_its_path_size_and_time_for_a_while, test_a_file_rewritten_in_place_is_rescanned_while_it_runs, test_a_file_rewritten_in_place_is_reported, test_the_watcher_on_linux_watches_with_inotify_and_hears_a_rewrite, tier 3: on each platform a file added in the file manager then retagged in another program then moved to another folder and removed shows each time in the library within seconds |
| R2.4 | When the platform can't watch that many folders | test_where_watching_stopped_gaining_focus_rescans_and_the_log_says_so, test_a_folder_the_system_refuses_stops_watching_and_the_log_says_why, test_the_folders_the_system_refuses_are_given_back_and_the_rest_watched, test_why_watching_stopped_names_linuxs_limit_where_it_has_one, tier 3: on Linux with fs.inotify.max_user_watches set below the root's folders MusiKata logs that it stopped watching and rescans when its window gains focus |

## 2.5. Songs, albums and artists

| Item | Sentence starts | Shown by |
|---|---|---|
| R2.5 | Songs, albums and artists | statement |
| R2.5.1 | A song is one audio file | test_a_scan_fills_the_index_and_a_second_reads_nothing |
| R2.5.1 | Its identity in the database is its path under the root | test_a_scan_finds_a_change_a_move_by_hash_a_removal_and_an_unreadable_file |
| R2.5.2 | An album is the songs that share an album artist and an album title | test_songs_sharing_an_album_artist_and_title_are_one_album_wherever_they_are, test_an_albums_row_summarizes_its_songs |
| R2.5.2 | A song without an album artist uses its artist | test_an_album_is_its_album_artist_or_else_artist_and_title_case_aside, test_songs_sharing_an_album_artist_and_title_are_one_album_wherever_they_are |
| R2.5.2 | Songs with the same album title in different folders | test_songs_sharing_an_album_artist_and_title_are_one_album_wherever_they_are, test_compilations_of_one_title_naming_no_album_artist_are_one_album_per_folder |
| R2.5.3 | A compilation is an album whose songs have different artists | test_a_compilation_is_flagged_songs_of_several_artists_or_various_artists, test_vorbis_keys_in_any_case_repeated_and_their_older_names, test_id3_frames_with_v23_dates_txxx_replaygain_and_comments, test_mp4_atoms_that_are_not_lists_compilation_gapless_and_tempo |
| R2.5.3 | It is listed once, under its album artist | test_a_compilation_is_listed_once_under_its_album_artist |
| R2.5.4 | An artist is anyone named as a song's artist or album artist | test_artists_named_in_another_case_are_one_shown_as_most_songs_name_them, test_artists_by_sort_name_with_their_counts_and_mosaic |
| R2.5.4 | Names that differ only in case are shown as one | test_artists_named_in_another_case_are_one_shown_as_most_songs_name_them |

## 2.7. Search

| Item | Sentence starts | Shown by |
|---|---|---|
| R2.7 | The header's search box (/ to focus it) filters the current view as the user types | test_slash_opens_the_search_typing_filters_and_escape_clears_it, test_a_search_filters_only_the_view_open_and_its_count_says_of_how_many, test_a_search_finds_its_rows_off_the_gui_thread_and_they_come_with_count_changed, test_albums_and_artists_a_search_finds_are_those_of_the_songs_it_finds, test_words_match_any_field_case_and_accents_aside, test_the_last_word_matches_as_its_prefix_while_typed, test_the_scan_keeps_song_fts_in_step_with_the_songs, test_a_field_narrows_its_word_or_phrase_to_its_columns_any_case, test_on_a_page_slash_opens_the_search_typing_filters_the_page_and_escape_clears_it, test_the_header_searches_an_albums_page_and_its_count_says_of_how_many, test_the_header_searches_an_artists_albums_and_other_songs_together, test_a_pages_search_is_kept_going_back_to_it_and_cleared_opening_it_anew |
| R2.7 | (rating:>=4) narrow a term to one field | test_a_field_narrows_its_word_or_phrase_to_its_columns_any_case, test_artist_reads_the_album_artist_too_and_album_only_the_album, test_ratings_and_years_compare_as_numbers, test_ratings_compare_and_a_song_not_rated_is_zero, test_the_header_searches_an_albums_page_and_its_count_says_of_how_many |

## 2.9. The Folders view

| Item | Sentence starts | Shown by |
|---|---|---|
| R2.9 | Folders browses the music root one folder at a time | test_folders_loads_in_every_mode_with_no_warning_and_its_text_in_its_boxes, test_folders_in_the_header_its_crumbs_count_modes_sort_and_search_hint, test_a_folder_lists_its_folders_then_its_files_with_their_crumbs_and_count |
| R2.9.1 | The header is the one Albums has (R6.4) | test_folders_in_the_header_its_crumbs_count_modes_sort_and_search_hint |
| R2.9.1 | In place of the view's title it shows the open folder's path under the root | test_a_folder_lists_its_folders_then_its_files_with_their_crumbs_and_count, test_clicks_select_open_and_play_folders_and_the_crumbs_and_keys_go_up_and_back |
| R2.9.1 | The root's own name, and any stand-in for it | test_the_root_lists_its_folders_by_name_titled_your_music_folders, test_folders_in_the_header_its_crumbs_count_modes_sort_and_search_hint |
| R2.9.1 | Beside the title is the open folder's count | test_the_root_lists_its_folders_by_name_titled_your_music_folders, test_a_folder_lists_its_folders_then_its_files_with_their_crumbs_and_count, test_going_up_and_back, test_going_up_is_alt_up_or_cmd_up_on_macos_and_backspace, test_clicks_select_open_and_play_folders_and_the_crumbs_and_keys_go_up_and_back, tier 3: on macOS ⌘↑ goes up a folder |
| R2.9.1 | Alt+← / the mouse's back button go back to the folder opened before | test_going_up_and_back, test_clicks_select_open_and_play_folders_and_the_crumbs_and_keys_go_up_and_back |
| R2.9.1 | Clicking Folders in the sidebar returns to the root | test_the_sidebars_folders_opens_where_it_was_left_and_again_returns_to_the_root, test_long_paths_fold_their_middle_crumbs_into_an_ellipsis, test_long_paths_fold_their_middle_crumbs_into_a_menu, test_the_open_folder_and_the_mode_are_remembered_for_next_time, later: #26 |
| R2.9.2 | The open folder's subfolders, then its own audio files | test_a_folder_lists_its_folders_then_its_files_with_their_crumbs_and_count, test_a_write_makes_a_row_for_each_folder_and_its_ancestors_with_their_counts |
| R2.9.2 | A folder with no audio file anywhere beneath it | test_scans_keep_the_rows_after_moves_and_deletes_up_through_the_ancestors, test_the_walk_skips_hidden_ignored_and_settings_folders_and_the_roots_own |
| R2.9.2 | Names sort as people read them | test_names_sort_as_people_read_them |
| R2.9.2 | Double-click or Enter opens a folder or plays a file | test_clicks_select_open_and_play_folders_and_the_crumbs_and_keys_go_up_and_back, test_play_plays_the_selections_first_song_and_activate_opens_or_plays |
| R2.9.2 | Search (R2.7) filters the open folder and everything beneath it | test_a_search_lists_the_folders_and_files_beneath_that_match_with_where_they_are, test_a_search_finds_folders_whose_names_hold_every_word_case_and_accents_aside, test_folders_loads_in_every_mode_with_no_warning_and_its_text_in_its_boxes |
| R2.9.3 | Each folder shows its own cover or a mosaic of the covers beneath it | test_a_folders_own_image_comes_first_then_the_embedded_cover_its_songs_share, test_a_mosaic_takes_up_to_four_subfolders_with_the_most_songs_in_name_order, test_a_folders_songs_sharing_an_embedded_cover_give_it_theirs, test_a_folders_mosaic_and_cover_are_shown_and_one_with_no_art_its_dashed_tile |
| R2.9.4 | View modes, chosen in the header's view switch, the same for every folder | test_folders_in_the_header_its_crumbs_count_modes_sort_and_search_hint, test_a_drag_box_and_lists_checkboxes_select_and_the_selection_stays_across_modes, test_the_open_folder_and_the_mode_are_remembered_for_next_time |
| R2.9.4 | In the three image modes the folder's own files follow the folders | test_a_folder_lists_its_folders_then_its_files_with_their_crumbs_and_count, test_folders_loads_in_every_mode_with_no_warning_and_its_text_in_its_boxes, later: #24 |
| R2.9.4 | \| Large images \| Covers about 220 px wide | test_folders_loads_in_every_mode_with_no_warning_and_its_text_in_its_boxes |
| R2.9.4 | \| Small images (default) \| Covers the size of Albums' | test_folders_in_the_header_its_crumbs_count_modes_sort_and_search_hint, test_folders_loads_in_every_mode_with_no_warning_and_its_text_in_its_boxes |
| R2.9.4 | \| Cards \| Wide cards like the Genres view's | test_folders_loads_in_every_mode_with_no_warning_and_its_text_in_its_boxes, later: #23 |
| R2.9.4 | \| List \| One table with Songs' columns | test_folders_loads_in_every_mode_with_no_warning_and_its_text_in_its_boxes, test_a_folders_list_row_shows_what_its_songs_share_and_their_total_time |
| R2.9.5 | Each folder carries the worst path-match state | later: #24 |
| R2.9.5 | A folder whose files all match shows nothing | later: #24 |
| R2.9.6 | Acting on a selection | statement |
| R2.9.6 | Folders and files are selected together | test_click_ctrl_click_shift_click_and_the_checkbox_select_folders_and_files, test_a_drag_box_and_lists_checkboxes_select_and_the_selection_stays_across_modes, test_clicks_select_open_and_play_folders_and_the_crumbs_and_keys_go_up_and_back |
| R2.9.6 | A selected folder stands for every song beneath it | test_a_selection_of_folders_resolves_to_the_songs_beneath_them, test_a_folder_and_a_file_inside_it_count_its_songs_once |
| R2.9.6 | The selection bar counts both | test_click_ctrl_click_shift_click_and_the_checkbox_select_folders_and_files, test_play_plays_the_selections_first_song_and_activate_opens_or_plays, test_clicks_select_open_and_play_folders_and_the_crumbs_and_keys_go_up_and_back, later: #22 |
| R2.9.6 | The same actions are in the right-click menu | later: #22 |
| R2.9.6 | Folders and files are dragged as R6.10 says | later: #24 |
| R2.9.7 | When the open folder holds audio files and no subfolders | test_a_folder_of_songs_has_its_strip_and_marks_the_values_that_differ, test_a_folder_of_songs_art_line_and_chip, later: #24 |
| R2.9.7 | Edit tags, Album art and Infer from path | later: #22 |
| R2.9.7 | Its files follow as a table | test_a_folder_of_songs_has_its_strip_and_marks_the_values_that_differ, test_values_that_differ_from_the_rest_of_a_folder_are_marked, later: #24 |
| R2.9.7 | The view switch stays, and applies again on leaving the folder | test_a_folder_of_songs_has_its_strip_and_marks_the_values_that_differ |

## 2.10. When the music root isn't there

| Item | Sentence starts | Shown by |
|---|---|---|
| R2.10 | When the music root isn't there | statement |
| R2.10 | If the root can't be reached when MusiKata starts, or goes away while it runs | test_a_root_that_isnt_there_is_scanned_without_taking_any_song_for_removed, test_a_root_that_goes_while_it_is_scanned_loses_nothing, test_a_root_not_there_at_start_keeps_its_library_and_says_so, test_a_root_that_goes_while_it_runs_is_found_gone_kept_and_rescanned_when_back, test_a_look_that_finds_the_root_gone_while_it_runs_keeps_the_library, test_a_root_that_isnt_there_opens_the_index_that_last_opened_it_making_nothing, test_a_root_that_isnt_there_finds_the_index_that_last_opened_it_touching_nothing, test_the_banner_names_the_root_or_the_linked_folders_out_of_reach, test_the_window_of_a_root_not_there_shows_its_banner_and_red_card, test_a_root_that_isnt_there_tours_its_library_as_it_was, tier 3: on each platform the music root's drive unplugged while MusiKata runs and plugged back keeps every song and shows then hides the banner |
| R2.10 | Its drive may be unplugged or its share not mounted | test_the_banner_names_the_root_or_the_linked_folders_out_of_reach, test_the_window_of_a_root_not_there_shows_its_banner_and_red_card, test_try_again_looks_now_and_a_root_still_gone_keeps_the_banner, test_choose_another_folder_says_which_when_it_is_a_folder, test_choose_another_folder_opens_it_in_the_windows_place_and_keeps_it, test_a_root_not_there_at_start_keeps_its_library_and_says_so, test_a_root_that_isnt_there_shows_its_covers_from_the_cache, test_a_song_whose_root_isnt_there_doesnt_play_and_says_why, test_a_root_that_goes_while_it_runs_is_found_gone_kept_and_rescanned_when_back, test_presence_looks_off_the_gui_thread_and_says_what_it_found, test_presence_looks_again_and_again_while_it_runs_and_not_once_stopped, test_a_look_that_fails_finds_nothing_there_and_the_log_says_so, test_a_root_gone_while_a_song_plays_lets_it_end_and_opens_nothing_after_it, test_a_root_gone_while_a_song_plays_greys_next_and_up_next_says_why, test_a_root_that_goes_while_it_runs_is_found_gone_kept_and_rescanned_when_back, later: #22 |
| R2.10 | A folder joined by a link (R2.3.2) that can't be reached | test_a_link_that_leads_nowhere_keeps_its_songs_and_is_named, test_a_linked_folder_that_cant_be_read_keeps_its_songs, test_a_folder_under_a_link_that_leads_nowhere_names_the_link, test_a_linked_folder_out_of_reach_makes_only_its_songs_unavailable, test_a_look_finds_the_root_and_the_linked_folders_still_out_of_reach |
| R2.10.1 | A scan that finds the root but more than a quarter of its songs, and more than 20, gone | test_more_than_a_quarter_and_more_than_20_gone_is_held_for_the_users_answer, test_a_quarter_is_of_the_whole_library_whichever_scan_finds_them_gone, test_a_scan_asks_first_over_a_quarter_and_over_20_gone, test_the_question_counts_the_songs_gone |
| R2.10.1 | Remove them from the library?", Keep them / Remove) | test_more_than_a_quarter_and_20_gone_asks_and_keep_them_keeps_them_unasked_after, test_a_few_songs_gone_are_taken_out_without_asking, test_remove_takes_the_songs_gone_out, test_a_remove_asked_for_while_a_scan_runs_waits_its_turn, test_songs_taken_out_on_remove_are_those_still_gone_while_the_root_is_there, test_the_question_of_songs_gone_is_answered_in_the_window |

## 2.13. Sort names

| Item | Sentence starts | Shown by |
|---|---|---|
| R2.13 | Artists, album artists and albums are shown as tagged and sorted by their sort names | test_without_a_sort_tag_a_leading_article_is_skipped_any_case, test_a_sort_tag_wins_over_the_name, test_sort_tags_win_for_the_album_artist_and_the_title, test_albums_by_album_artist_then_title_by_their_sort_names, test_artists_by_sort_name_with_their_counts_and_mosaic, test_the_songs_list_sorts_artists_by_their_sort_names, test_a_name_that_only_looks_like_an_article_is_kept, test_a_name_with_an_article_sorts_as_the_name_without_it |
| R2.13 | The, A and An, a list in Settings (R13.3) | test_the_articles_are_a_list_others_can_be_added_to, test_case_and_leading_punctuation_are_set_aside, test_numbers_are_read_by_value, test_any_numbers_sort_by_value_in_a_name, test_no_name_has_no_key_so_it_sorts_last_in_sql |

## 4.7. Writing

| Item | Sentence starts | Shown by |
|---|---|---|
| R4.7 | Saving writes each file in turn, shows progress for more than a few files, and can be cancelled between files | test_each_file_is_written_in_turn_with_progress_after_each, test_cancelled_it_stops_before_the_next_file_never_inside_one, test_it_runs_off_the_calling_thread_and_a_cancel_from_another_stops_it, later: #22 |
| R4.7 | A file is never left half written: each is written in full beside the original and then put in its place (A3.4) | test_a_song_is_written_as_a_copy_beside_it_flushed_checked_then_put_in_its_place, test_a_write_interrupted_at_any_step_leaves_the_song_as_it_was, test_tags_that_dont_read_back_as_written_leave_the_song_as_it_was, test_a_cover_or_audio_that_doesnt_read_back_leaves_the_song_as_it_was, test_a_copy_a_write_left_behind_is_never_a_song_and_the_next_scan_removes_it, test_a_leftover_copy_is_removed_once_untouched_for_a_while_never_while_being_written |
| R4.7 | Read-only files, files in use and files that fail are listed at the end with their reason and a Retry; the others are saved | test_the_files_that_fail_are_listed_with_why_and_the_others_saved, test_a_read_only_song_is_reported_and_never_touched, test_each_failure_says_what_happened_and_what_to_do, test_a_song_gone_or_that_cant_be_read_says_so, tier 3: on Windows a song open in another program is listed as open there when saved and is saved by Retry once closed, later: #22 |
| R4.7.1 | By default a written file's modification time is updated | test_the_songs_permissions_are_kept_and_its_modification_time_updated_or_kept, test_the_roots_own_settings_give_the_id3_version_and_whether_times_are_kept |
| R4.7.1 | A setting (R13) keeps it as it was, for backup tools that go by it | test_the_songs_permissions_are_kept_and_its_modification_time_updated_or_kept, test_the_roots_own_settings_give_the_id3_version_and_whether_times_are_kept, test_the_roots_tags_values_broken_or_in_another_form, test_a_file_musikata_wrote_has_its_row_updated_from_what_was_written_and_isnt_read_again, later: #26 |
| R4.7.2 | MP3s are written as ID3v2.4, or ID3v2.3 when Settings says so (R13), for older players and car stereos | test_id3v24_or_id3v23_as_the_setting_says_and_v23_genres_joined, test_each_kind_reads_back_every_field_written_and_none_once_each_is_removed, test_frames_mutagen_doesnt_know_and_v24s_sort_names_survive_either_version, test_the_roots_own_settings_give_the_id3_version_and_whether_times_are_kept, later: #26 |
| R4.7.2 | An ID3v1 tag already in a file is updated to match; none is added | test_an_id3v1_tag_is_updated_to_match_and_none_is_added, test_the_demo_librarys_files_of_every_kind_and_shape_are_written_and_read_back |

## 7.1. Playing

| Item | Sentence starts | Shown by |
|---|---|---|
| R7.1 | Double-clicking a song, or pressing Enter on a selection | test_playing_a_song_puts_the_rest_of_its_list_after_it, test_a_double_click_plays_the_song_and_queues_the_rest_of_its_list, test_a_right_click_on_a_song_offers_play_next_and_add_to_queue, test_double_clicking_a_song_plays_it_and_marks_its_row, test_play_plays_the_selections_first_song_and_activate_opens_or_plays, test_clicks_select_open_and_play_folders_and_the_crumbs_and_keys_go_up_and_back, test_an_albums_page_says_what_it_holds, later: #22 |
| R7.1 | Play on an album, artist, genre or playlist does the same from its first song | test_play_on_an_album_plays_from_its_first_song, test_play_on_an_album_plays_it_from_its_first_song_and_shuffle_from_any, test_clicks_open_a_view_an_album_its_artist_and_go_back, test_play_plays_the_selections_first_song_and_activate_opens_or_plays, later: #23 |

## 7.2. The queue

| Item | Sentence starts | Shown by |
|---|---|---|
| R7.2 | The queue button in the now-playing bar opens Up next | test_the_queue_button_opens_up_next_and_closes_it_again, test_the_bar_shows_the_song_and_its_buttons_play_it, test_play_next_and_add_to_queue_put_a_rows_songs_where_they_say, test_up_next_lists_the_songs_played_last_the_latest_first, test_an_empty_up_next_says_so_and_a_song_gone_says_that, test_the_bar_and_up_next_keep_their_text_in_their_boxes_at_both_sizes |
| R7.2 | Now Playing with No visualization shows the same queue at full size | later: #25 |
| R7.2 | Songs can be reordered and removed there, and dropped onto it | test_a_row_of_up_next_plays_moves_or_goes_at_a_click, test_a_song_to_come_moves_where_it_is_dropped, test_remove_takes_a_song_to_come_or_played_out_and_the_current_one_stays, test_a_move_while_shuffling_leaves_the_order_shuffle_off_returns_to, later: #24 |
| R7.2 | Every song list's context menu has Play next and Add to queue | test_play_next_goes_right_after_the_current_song_ahead_of_songs_added_before, test_add_to_queue_goes_after_the_songs_added_before_and_ahead_of_the_rest_of_the_list, test_songs_added_to_an_empty_or_played_out_queue_are_cued_there, test_play_next_and_add_to_queue_put_a_rows_songs_where_they_say, test_a_right_click_on_a_song_offers_play_next_and_add_to_queue, test_a_rows_songs_are_what_its_menu_queues_and_the_roots_name_is_its_title, later: #23 |
| R7.2 | The queue is kept across restarts | test_a_root_opens_with_what_was_playing_when_it_closed_paused_at_its_place, test_a_song_moved_is_found_by_its_hash_and_one_gone_leaves_the_queue, test_a_kept_file_broken_by_a_sync_starts_an_empty_queue_and_says_so, test_a_restored_queue_is_cued_at_its_place_and_play_goes_on_from_there, test_a_queue_kept_across_a_restart_plays_on_from_its_place, test_what_plays_is_kept_when_the_queue_changes_on_pause_once_a_minute_and_at_close, test_at_close_what_changed_since_the_last_write_is_kept, test_a_queue_restored_is_cued_on_its_current_song_with_what_the_user_added, test_a_kept_queue_saved_and_restored_is_the_same_queue, test_what_is_written_is_valid_and_reads_back_as_the_same_queue, test_a_queue_restored_is_the_one_kept, test_songs_gone_leave_the_queue_and_a_current_one_gone_gives_way_to_the_next, test_with_both_copies_the_roots_is_read_when_it_is_the_newer, test_keeping_writes_off_the_callers_thread_making_this_computers_id_once |

## 7.3. Shuffle and repeat

| Item | Sentence starts | Shown by |
|---|---|---|
| R7.3 | Shuffle plays the queue in a random order without repeating a song until all have played | test_shuffle_plays_every_song_once_before_any_plays_again, test_a_seeded_shuffle_gives_the_same_order_every_time, test_shuffle_keeps_the_songs_added_first_and_off_puts_the_rest_back_in_order, test_a_shuffled_lap_with_repeat_all_never_starts_with_the_song_that_just_ended, test_shuffled_play_of_a_list_starts_from_the_song_chosen_or_one_at_random, test_shuffle_and_repeat_buttons_say_their_state, test_the_bar_shows_the_song_and_its_buttons_play_it |
| R7.3 | Repeat cycles Off, All and One | test_repeat_cycles_off_all_one_and_off, test_repeat_all_plays_the_queue_again_from_its_start, test_repeat_one_plays_the_song_again_when_it_ends_and_next_still_moves_on, test_shuffle_and_repeat_buttons_say_their_state, test_the_bar_shows_the_song_and_its_buttons_play_it |
| R7.3 | Both are kept across restarts | test_a_root_opens_with_what_was_playing_when_it_closed_paused_at_its_place, test_shuffle_and_repeat_start_as_the_settings_have_them_and_changes_are_kept, test_shuffle_or_repeat_set_keeps_the_rest_of_the_file_valid_under_its_schema, test_shuffle_and_repeat_are_read_from_playback, test_shuffle_and_repeat_are_kept_on_its_thread_in_the_order_asked, test_a_shuffled_queue_restored_comes_back_in_its_order_and_shuffle_off_finds_the_one_before, test_a_restored_queue_with_repeat_all_draws_its_next_lap_afresh |

## 7.4. Seeking

| Item | Sentence starts | Shown by |
|---|---|---|
| R7.4 | Clicking or dragging on the waveform in the now-playing bar or in Now Playing seeks there (R11.2) | test_the_seek_bar_seeks_where_it_is_clicked_and_dragged, test_a_seek_shows_the_place_at_once_and_holds_it_until_the_engine_is_there, test_a_seek_moves_the_sound_and_the_position_follows_from_there, test_a_seek_replaces_what_the_ring_holds_with_the_song_from_there, test_a_seek_lands_on_the_exact_sample, test_left_and_right_seek_five_seconds_unless_a_list_or_box_uses_them, later: #25 |

## 7.5. ReplayGain

| Item | Sentence starts | Shown by |
|---|---|---|
| R7.5 | Track, Album (the default) or Off, a setting (R13) | test_album_is_the_album_gain_in_order_and_the_track_gain_otherwise, test_track_off_and_the_pre_amp_are_the_settings, test_a2_10s_playback_gives_the_device_replaygain_and_its_pre_amp, test_playback_values_broken_in_another_case_or_as_text, later: #26 |
| R7.5 | Album uses the album gain when the album is played in order and the track gain otherwise | test_album_is_the_album_gain_in_order_and_the_track_gain_otherwise, test_a_song_with_one_gain_uses_it_whichever_is_asked_for, test_an_album_is_in_order_from_any_of_its_songs_on_and_a_song_alone_isnt, test_an_album_played_in_order_plays_at_its_album_gain_song_after_song, test_an_album_from_its_second_song_on_is_in_order_and_one_song_alone_isnt, test_songs_out_of_their_albums_order_play_at_their_track_gains, test_a_song_repeated_keeps_its_gain_and_a_file_outside_the_index_has_the_pre_amp, test_a_gain_is_held_under_the_peak_so_it_never_clips, test_no_gain_takes_a_peak_past_full_scale, test_each_song_plays_at_its_gain_and_a_change_ramps_over_50_ms_from_the_join |
| R7.5 | Songs without ReplayGain tags play at a pre-amp of −6 dB so they aren't louder than those with them | test_a_song_without_replaygain_plays_at_the_pre_amp, test_songs_out_of_their_albums_order_play_at_their_track_gains, test_track_off_and_the_pre_amp_are_the_settings, test_a_song_plays_at_the_replaygain_it_was_asked_with |
| R7.5 | MusiKata reads ReplayGain | test_each_kind_gives_its_replaygain_as_its_taggers_write_it, test_an_mp3s_replaygain_in_rva2_frames_or_an_apev2_tag, test_opus_r128_gains_win_over_its_replaygain_keys_and_carry_no_peak, test_replaygain_reads_db_and_peaks_in_their_written_forms |

## 7.6. Between songs

| Item | Sentence starts | Shown by |
|---|---|---|
| R7.6 | Playback is gapless | test_a_song_runs_into_the_next_with_no_frame_lost_or_added, test_any_songs_join_frame_for_frame_whatever_the_device_reads, test_songs_of_one_rate_join_as_if_they_were_one_song, test_songs_of_the_queue_join_in_one_stream_the_sink_never_stopped, test_a_next_song_changed_before_the_device_reached_it_is_replaced_with_no_gap, test_a_seek_into_the_last_seconds_opens_the_next_song_and_joins_it, test_an_mp3s_start_delay_and_end_padding_from_its_lame_header_are_left_out, test_an_aac_files_priming_and_padding_from_its_itunsmpb_tag_are_left_out, test_an_aac_files_priming_and_padding_from_its_edit_list_are_left_out |
| R7.6 | This holds across songs of different sample rates and kinds | test_songs_of_other_rates_and_channels_join_each_at_its_exact_length, test_a_tone_going_on_across_songs_of_other_rates_doesnt_click_at_the_seam, test_each_kind_decodes_to_its_length_and_pitch_at_the_devices_rate, test_an_opus_files_pre_skip_and_end_are_left_out |
| R7.6 | Crossfading is | statement |
| R7.6.1 | The equalizer (R19) and ReplayGain (R7.5) apply to the same stream | test_each_song_plays_at_its_gain_and_a_change_ramps_over_50_ms_from_the_join, test_a_change_of_gain_across_rates_ramps_from_the_seam_too, test_no_frame_of_a_ramp_steps_more_than_its_slope_allows, test_a_join_with_no_change_of_gain_isnt_ramped_and_a_song_alone_has_its_gain, test_a_song_shorter_than_the_ramp_hands_on_the_gain_it_reached, later: #26 |

## 7.7. Output

| Item | Sentence starts | Shown by |
|---|---|---|
| R7.7 | The output device is the system's default unless one is chosen in Settings (R13) | test_the_device_chosen_is_played_on_when_it_is_there_else_the_default, test_the_engine_plays_on_the_device_chosen_in_settings, test_a_device_that_goes_away_pauses_and_moves_to_the_default_from_the_same_sample, test_another_device_going_away_changes_nothing, test_a_new_device_goes_on_from_the_frame_the_old_one_had_played, test_a_new_device_of_another_rate_hears_the_song_on_from_the_same_instant, tier 3: on each platform headphones or a USB DAC unplugged while a song plays pause it and play goes on from the same place on the default device, later: #26 |

## 7.8. The system's controls

| Item | Sentence starts | Shown by |
|---|---|---|
| R7.8 | The system's controls | statement |
| R7.8 | MusiKata shows the song and its cover and takes play, pause, next, previous and seek from the system | test_nothing_is_shown_until_a_song_is_and_then_its_words_and_playing, test_the_cover_is_found_off_the_gui_thread_and_the_song_shown_again_with_it, test_a_thumbnails_file_is_found_or_made_for_the_systems_media_controls, test_pause_and_a_seek_are_told_and_a_restart_is_a_seek, test_a_position_that_isnt_where_playing_on_would_put_it_is_a_seek, test_each_song_shown_is_a_new_track_and_none_is_no_track, test_each_command_does_what_it_says_when_it_can, test_the_systems_commands_work_the_player_the_window_and_quit, test_a_command_sent_from_another_thread_is_obeyed_on_the_gui_thread, test_a_backend_that_cant_start_leaves_playback_as_it_was_and_says_so_once, test_a_platform_without_controls_plays_and_says_so, test_each_platform_has_its_backend_and_others_none |
| R7.8 | MPRIS over D-Bus, so the desktop's media keys and sound menu work | test_the_desktop_finds_musikata_on_the_bus_and_what_it_can_do, test_the_desktop_sees_the_song_its_cover_and_where_it_is_in_d_buss_types, test_the_desktop_hears_each_change_and_each_seek, test_the_desktops_commands_are_obeyed, test_a_second_musikata_takes_a_name_of_its_own_and_each_gives_its_up, test_without_a_session_bus_it_doesnt_start_and_says_why, test_mpris_metadata_has_each_key_the_song_has_and_lengths_in_microseconds, test_the_player_properties_follow_the_state_and_only_those_that_changed_are_sent, test_windows_controls_are_on_with_every_button_off_until_a_song_is_shown, test_windows_shows_the_songs_words_cover_and_timeline, test_windows_buttons_and_the_position_moved_are_commands, test_windows_controls_let_go_when_closed, tier 3: on Linux Mint 22.3 and LMDE 7 and Ubuntu 26.04 the sound menu shows the song and its cover and its media keys play and pause and skip and seek it, tier 3: on Windows 10 and 11 the media keys play and pause and skip the song and the volume overlay shows it with its cover |
| R7.8 | Now Playing in Control Centre and the media keys | test_macos_shows_the_song_its_cover_and_where_it_is_moving_on_while_it_plays, test_macos_commands_and_the_position_moved_are_commands, test_macos_lets_go_of_the_commands_and_clears_now_playing_when_closed, test_a_file_urls_path_is_the_file_it_names, tier 3: on macOS Control Centre's Now Playing shows the song and its cover and where it is and the media keys play and pause and skip it and its bar seeks |
