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
- `later: #n`, the `future` issue the sentence waits on;
- `statement`: it explains, names a file or a limit, and promises nothing a test could show.

**Sentence starts** is the sentence's opening words, with Markdown emphasis and backticks dropped.
A table row is traced whole, its cells as written.

## 2.5. Songs, albums and artists

| Item | Sentence starts | Shown by |
|---|---|---|
| R2.5 | Songs, albums and artists | statement |
| R2.5.1 | A song is one audio file | test_a_scan_fills_the_index_and_a_second_reads_nothing |
| R2.5.1 | Its identity in the database is its path under the root | test_a_scan_finds_a_change_a_move_by_hash_a_removal_and_an_unreadable_file |
| R2.5.2 | An album is the songs that share an album artist and an album title | test_songs_sharing_an_album_artist_and_title_are_one_album_wherever_they_are, test_an_albums_row_summarizes_its_songs |
| R2.5.2 | A song without an album artist uses its artist | test_an_album_is_its_album_artist_or_else_artist_and_title_case_aside, test_songs_sharing_an_album_artist_and_title_are_one_album_wherever_they_are |
| R2.5.2 | Songs with the same album title in different folders | test_songs_sharing_an_album_artist_and_title_are_one_album_wherever_they_are |
| R2.5.3 | A compilation is an album whose songs have different artists | test_a_compilation_is_flagged_songs_of_several_artists_or_various_artists, test_vorbis_keys_in_any_case_repeated_and_their_older_names, test_id3_frames_with_v23_dates_txxx_replaygain_and_comments, test_mp4_atoms_that_are_not_lists_compilation_gapless_and_tempo |
| R2.5.3 | It is listed once, under its album artist | test_a_compilation_is_listed_once_under_its_album_artist |
| R2.5.4 | An artist is anyone named as a song's artist or album artist | test_artists_named_in_another_case_are_one_shown_as_most_songs_name_them, test_artists_by_sort_name_with_their_counts_and_mosaic |
| R2.5.4 | Names that differ only in case are shown as one | test_artists_named_in_another_case_are_one_shown_as_most_songs_name_them |

## 2.7. Search

| Item | Sentence starts | Shown by |
|---|---|---|
| R2.7 | The header's search box (/ to focus it) filters the current view as the user types | test_slash_opens_the_search_typing_filters_and_escape_clears_it, test_a_search_filters_only_the_view_open_and_its_count_says_of_how_many, test_a_search_finds_its_rows_off_the_gui_thread_and_they_come_with_count_changed, test_albums_and_artists_a_search_finds_are_those_of_the_songs_it_finds, test_words_match_any_field_case_and_accents_aside, test_the_last_word_matches_as_its_prefix_while_typed, test_the_scan_keeps_song_fts_in_step_with_the_songs, test_a_field_narrows_its_word_or_phrase_to_its_columns_any_case |
| R2.7 | (rating:>=4) narrow a term to one field | test_a_field_narrows_its_word_or_phrase_to_its_columns_any_case, test_artist_reads_the_album_artist_too_and_album_only_the_album, test_ratings_and_years_compare_as_numbers, test_ratings_compare_and_a_song_not_rated_is_zero |

## 2.13. Sort names

| Item | Sentence starts | Shown by |
|---|---|---|
| R2.13 | Artists, album artists and albums are shown as tagged and sorted by their sort names | test_without_a_sort_tag_a_leading_article_is_skipped_any_case, test_a_sort_tag_wins_over_the_name, test_sort_tags_win_for_the_album_artist_and_the_title, test_albums_by_album_artist_then_title_by_their_sort_names, test_artists_by_sort_name_with_their_counts_and_mosaic, test_the_songs_list_sorts_artists_by_their_sort_names, test_a_name_that_only_looks_like_an_article_is_kept, test_a_name_with_an_article_sorts_as_the_name_without_it |
| R2.13 | The, A and An, a list in Settings (R13.3) | test_the_articles_are_a_list_others_can_be_added_to, test_case_and_leading_punctuation_are_set_aside, test_numbers_are_read_by_value, test_any_numbers_sort_by_value_in_a_name, test_no_name_has_no_key_so_it_sorts_last_in_sql |
