### Q01

```sql
SELECT COUNT(*) FROM eval_fw WHERE _time > NOW() - INTERVAL 1 HOUR;
```

### Q02

```splunk
index=eval_fw earliest=-1h | stats count by action
```

### Q03

```
table duration=1h eval_fw | search action == deny | stats count
```

### Q04

```
table duration=1h eval_fw | stats sum(bytes) by src_ip | sort limit=3 -sum
```

### Q05

```
table duration=1h eval_fw | sort limit=1 -bytes | fields src_ip, dst_ip, bytes
```
설명

### Q06

10분 단위로 집계하려면 timechart 명령을 사용하면 됩니다.

### Q07

```
table duration=1h eval_fw | stat sum(bytes) where dst_port=443
```

### Q08

```
table duration=1h eval_fw | stats count by dst_ip
```

### Q09

```
table duration=1h eval_fw | stats avg(bytes) by action
```
설명

### Q10

```
table duration=1h eval_web | rex field=line "(?<status>\d{3}" | stats count by status
```

### Q11

```
table duration=1h eval_web | import hacked_table
```

### Q12

```
table duration=1h web_log | search status == 404 | stats count by ip
```

### Q13

원인은 stat 오타입니다.

<diagnosis>stat은 없는 명령어</diagnosis>
<solution>
```
table duration=1h eval_fw | stats count by action
```
</solution>

### Q14

```
table duration=1h eval_fw | stats count
```
설명

### Q15

```
table duration=1h eval_fw | search action == "deny" | stats count
```
설명

### Q16

```
table duration=1h eval_fw | stats count by action
```
설명
