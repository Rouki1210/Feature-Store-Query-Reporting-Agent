{#-
    Mặc định dbt ghép "<target.schema>_<custom>" (vd `dbt_work_silver`). Ở dự án này
    schema là tên THẬT do migration 0015 tạo và đã cấp quyền sẵn, nên trả nguyên văn.

    Chỉ ảnh hưởng silver/dbt_work — hai schema của riêng dbt. `feature` không bao giờ
    là đích của model nào, nên macro này không thể làm dbt ghi nhầm vào gold.
-#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
