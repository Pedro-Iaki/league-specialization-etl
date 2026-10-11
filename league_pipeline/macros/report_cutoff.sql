{% macro report_cutoff() %}
    {% set cutoff = var('report_as_of_date', none) %}
    {% if cutoff is not none %}
        {% set validated = modules.datetime.datetime.strptime(cutoff | string, '%Y-%m-%d') %}
        cast('{{ cutoff }}' as date)
    {% else %}
        (select max(snapshot_date) from {{ ref('dim_players_current') }})
    {% endif %}
{% endmacro %}
