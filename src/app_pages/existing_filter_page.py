# src/app_pages/existing_filter_page.py
import streamlit as st
import pandas as pd
import re
from datetime import datetime, timedelta, time, date
import csv # csv モジュールをインポート済み

# utilsからparse_syslog_lineをインポート
from src.utils.log_parser_utils import parse_syslog_line

# --- フィルタ管理用のヘルパー関数 (オリジナルのapp.pyからコピー) ---
def add_filter():
    st.session_state.filters_keyword_page.append({"keyword": "", "operator": "AND"})

def remove_filter(index):
    if len(st.session_state.filters_keyword_page) > 1:
        st.session_state.filters_keyword_page.pop(index)
    else:
        st.session_state.filters_keyword_page[0]["keyword"] = ""
        st.session_state.filters_keyword_page[0]["operator"] = "AND"

def update_filter_keyword(index):
    st.session_state.filters_keyword_page[index]["keyword"] = st.session_state[f"filter_keyword_{index}"]

def update_filter_operator(index):
    st.session_state.filters_keyword_page[index]["operator"] = st.session_state[f"filter_operator_{index}"]

def convert_wildcard_to_regex(pattern):
    escaped_pattern = re.escape(pattern)
    escaped_pattern = escaped_pattern.replace(r'\*', '.*')
    escaped_pattern = escaped_pattern.replace(r'\?', '.')
    return escaped_pattern

# --- 時間選択肢の生成ヘルパー関数 ---
def generate_time_options(interval_minutes=5):
    times = []
    start = datetime.strptime("00:00", "%H:%M")
    end = datetime.strptime("23:59", "%H:%M")
    current = start
    while current <= end:
        times.append(current.strftime("%H:%M"))
        current += timedelta(minutes=interval_minutes)
    return times
# --- ヘルパー関数ここまで ---

def run():
    st.title("Syslog Filter (キーワードフィルタリング)")

    df_source = st.session_state.df_filtered if 'df_filtered' in st.session_state and not st.session_state.df_filtered.empty else st.session_state.df
    
    if 'filters_keyword_page' not in st.session_state:
        st.session_state.filters_keyword_page = [{"keyword": "", "operator": "AND"}]

    if not df_source.empty:
        st.write(f"元のログの行数: {len(df_source)}行")

        # 日時によるフィルタリング設定を表示するExpander
        if 'datetime_spec_conditions' in st.session_state:
            conditions = st.session_state.datetime_spec_conditions
            with st.expander("日時絞り込みの現在の設定を表示"):
                start_time_str_display = f"{conditions.get('start_hour', '00')}:{conditions.get('start_minute', '00')}"
                end_time_str_display = f"{conditions.get('end_hour', '23')}:{conditions.get('end_minute', '59')}"
                
                st.write(f"**開始日時**: {conditions.get('start_date', '未設定')} {start_time_str_display}")
                st.write(f"**終了日時**: {conditions.get('end_date', '未設定')} {end_time_str_display}")
                st.write(f"**絞り込み済みログ数**: {conditions.get('filtered_count', 'N/A')}行")

        st.subheader("キーワードによるフィルタリング")
        st.info("キーワードで **`*` は0文字以上の任意の文字、**`?` は任意の1文字**を表します。")

        search_cols_source = ['Timestamp', 'Hostname', 'AppName', 'PID', 'Message']

        for i, filter_item in enumerate(st.session_state.filters_keyword_page):
            col_op, col_kw, col_btn = st.columns([1, 4, 1])

            with col_op:
                if i == 0:
                    st.write("")
                else:
                    st.selectbox(
                        "演算子",
                        ["AND", "OR"],
                        index=0 if filter_item["operator"] == "AND" else 1,
                        key=f"filter_operator_{i}",
                        label_visibility="collapsed",
                        on_change=update_filter_operator,
                        args=(i,)
                    )
            with col_kw:
                st.text_input(
                    "キーワード",
                    value=filter_item["keyword"],
                    key=f"filter_keyword_{i}",
                    label_visibility="collapsed",
                    on_change=update_filter_keyword,
                    args=(i,)
                )
            with col_btn:
                if len(st.session_state.filters_keyword_page) > 1:
                    st.button("削除", key=f"remove_filter_{i}", on_click=remove_filter, args=(i,))
                else:
                    st.write("")

        st.button("フィルタ追加", on_click=add_filter, key="add_filter_button_keyword_page")
        st.markdown("---")

        filtered_df = df_source.copy()

        if not df_source.empty:
            # Timestamp を文字列として結合 (検索用)
            df_for_search = filtered_df.copy()
            if 'Timestamp' in df_for_search.columns and pd.api.types.is_datetime64_any_dtype(df_for_search['Timestamp']):
                df_for_search['Timestamp_str'] = df_for_search['Timestamp'].dt.strftime('%Y-%m-%dT%H:%M:%S.%f')
            
            search_cols_to_join = [col if col != 'Timestamp' else 'Timestamp_str' for col in search_cols_source]
            search_cols_to_join = [col for col in search_cols_to_join if col in df_for_search.columns]

            combined_text_series = df_for_search[search_cols_to_join].fillna('').astype(str).agg(' '.join, axis=1)

            # キーワードフィルタリングロジック (combined_text_series を使用)
            if st.session_state.filters_keyword_page:
                current_filter_series = None
                
                first_condition_keyword = st.session_state.filters_keyword_page[0]['keyword'].strip()
                if first_condition_keyword:
                    first_regex = convert_wildcard_to_regex(first_condition_keyword)
                    current_filter_series = combined_text_series.str.contains(first_regex, case=False, na=False, regex=True)
                else:
                    current_filter_series = pd.Series([True] * len(filtered_df), index=filtered_df.index)
                    
                for i in range(1, len(st.session_state.filters_keyword_page)):
                    condition = st.session_state.filters_keyword_page[i]
                    keyword = condition['keyword'].strip()
                    operator = condition['operator']
                    if not keyword:
                        continue

                    regex_keyword = convert_wildcard_to_regex(keyword)
                    current_condition = combined_text_series.str.contains(regex_keyword, case=False, na=False, regex=True)

                    if operator == "AND":
                        current_filter_series = current_filter_series & current_condition
                    elif operator == "OR":
                        current_filter_series = current_filter_series | current_condition
                
                if current_filter_series is not None:
                    filtered_df = filtered_df[current_filter_series]
                else:
                    filtered_df = pd.DataFrame()
        
        st.subheader("表示設定")
        
        all_available_cols = ['Timestamp', 'Hostname', 'AppName', 'PID', 'Message']
        available_cols_in_df = [col for col in all_available_cols if col in filtered_df.columns]

        st.markdown("**表示・出力する列を選択してください**")
        col_checkboxes = st.columns(len(available_cols_in_df))
        
        selected_display_cols = []
        for i, col in enumerate(available_cols_in_df):
            default_checked = (col == 'Timestamp' or col == 'Message')
            
            if f"display_col_{col}" not in st.session_state:
                st.session_state[f"display_col_{col}"] = default_checked
            
            with col_checkboxes[i]:
                if st.checkbox(col, value=st.session_state[f"display_col_{col}"], key=f"checkbox_col_{col}"):
                    selected_display_cols.append(col)

        max_rows = st.slider("表示する最大行数", 100, 1000000, 2000, key="max_rows_filter_page")

        st.subheader("フィルタリング結果")
        if not filtered_df.empty and selected_display_cols:
            st.write(f"表示中のログ数: {len(filtered_df)}行")
            
            if len(filtered_df) > max_rows:
                st.info(f"上位 {max_rows} 行のみ表示しています。")

            display_df_selected_cols = filtered_df[selected_display_cols].copy()
            if 'Timestamp' in display_df_selected_cols.columns and pd.api.types.is_datetime64_any_dtype(display_df_selected_cols['Timestamp']):
                display_df_selected_cols['Timestamp'] = display_df_selected_cols['Timestamp'].dt.strftime('%Y-%m-%dT%H:%M:%S.%f')
            
            st.dataframe(
                display_df_selected_cols.tail(max_rows),
                use_container_width=True,
                height=1000
            )

            # --- 修正箇所: CSVダウンロード時に quoting と escapechar を設定 ---
            csv_data = filtered_df[selected_display_cols].to_csv(index=False, quoting=csv.QUOTE_ALL, escapechar='\\').encode('utf-8')
            # ----------------------------------------------------------------
            st.download_button(
                label="表示中のデータフレームをCSVでダウンロード",
                data=csv_data,
                file_name='filtered_syslog_data.csv',
                mime='text/csv',
                key="download_filtered_output_csv_keyword_page"
            )
            
            log_lines_output = []
            for _, row in filtered_df.iterrows():
                parts = []
                for col in selected_display_cols:
                    value = row[col]
                    if pd.isna(value):
                        parts.append("")
                    elif col == 'Timestamp':
                        parts.append(value.isoformat() if pd.notna(value) else "")
                    elif col == 'PID':
                        parts.append(f"[{int(value)}]" if pd.notna(value) else "")
                    else:
                        parts.append(str(value))
                
                log_line = " ".join(parts).strip()
                log_lines_output.append(log_line)
            
            log_data_filtered = "\n".join(log_lines_output).encode('utf-8')
            st.download_button(
                label="フィルタリング結果をLOGでダウンロード",
                data=log_data_filtered,
                file_name='filtered_syslog_data.log',
                mime='text/plain',
                key="download_filtered_output_log_keyword_page"
            )
        elif not filtered_df.empty and not selected_display_cols:
            st.warning("表示する列が選択されていません。列を選択してください。")
        else:
            st.info("表示するログがありません。フィルタリング条件を確認してください。")
    else:
        st.warning("ログデータが読み込まれていません。「データ読み込み」ページでファイルをアップロードするか、「日時指定・抽出」ページでログを絞り込んでください。")