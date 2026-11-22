// stdin 으로 ELK 그래프(JSON)를 받아 배치 결과(JSON)를 stdout 으로 낸다.
const ELK = require('elkjs');
let input = '';
process.stdin.on('data', (c) => { input += c; });
process.stdin.on('end', async () => {
  const graph = JSON.parse(input);
  const result = await new ELK().layout(graph);
  process.stdout.write(JSON.stringify(result));
});
