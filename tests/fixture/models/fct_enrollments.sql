select s.student_id, s.school_id, s.exit_code
from {{ ref('stg_students') }} as s
inner join {{ ref('dim_schools') }} as d on s.school_id = d.school_id
