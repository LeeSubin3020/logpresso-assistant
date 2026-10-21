### Q01

```
table duration=1h eval_fw | stats count as total
```

### Q02

```
table duration=1h eval_fw | stats count as cnt by action
```

### Q03

```
table duration=1h eval_fw | search action == "deny" | stats count
```
설명

### Q04

```
table duration=1h eval_fw | stats sum(bytes) as total by src_ip | sort limit=3 -total
```
설명

### Q05

```
table duration=1h eval_fw | sort limit=1 -bytes | fields src_ip, dst_ip, bytes
```
설명

### Q06

```
table duration=1h eval_fw | timechart span=10m count
```
설명

### Q07

```
table duration=1h eval_fw | search dst_port == 443 and action == "allow" | stats sum(bytes)
```
설명

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
table duration=1h eval_web | rex field=line "\" (?<status>\d{3}) " | stats count by status
```
설명

### Q11

```
table duration=1h eval_web | rex field=line "\"(?<method>[A-Z]+) (?<path>\S+) " | stats count by path | sort limit=3 -count
```
설명

### Q12

```
table duration=1h eval_web | rex field=line "^(?<ip>\S+) .*\" (?<status>\d{3}) " | search status == "404" | stats count by ip
```
설명

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
