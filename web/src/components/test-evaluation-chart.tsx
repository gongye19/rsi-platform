'use client';
import {CartesianGrid,Line,LineChart,XAxis,YAxis} from 'recharts';
import {ChartContainer,ChartTooltip,ChartTooltipContent} from '@/components/ui/chart';
import {testResults} from '@/lib/test-results';
import type {Run} from '@/lib/console-types';

const config={score:{label:'TEST score',color:'#5e6ad2'}};
const percent=(value:number)=>`${(value*100).toFixed(1)}%`;

export default function TestEvaluationChart({tests,selectedVersion}:{tests:Run['tests'];selectedVersion?:string}) {
  const points=testResults(tests,selectedVersion);
  if(!points.some(point=>point.score!==null))return <div className="ce-test-empty"><strong>No TEST results yet</strong><span>Held-out evaluation runs after training and version selection.</span></div>;
  return <div className="ce-chart-scroll ce-test-chart" aria-label="Held-out TEST baseline and final scores">
    <div className="ce-test-heading">Held-out TEST</div>
    <ChartContainer config={config} className="ce-recharts" initialDimension={{width:800,height:400}}>
      <LineChart accessibilityLayer data={points} margin={{top:24,right:30,bottom:16,left:12}}>
        <CartesianGrid vertical={false} stroke="#e6e9ef" strokeDasharray="3 5"/>
        <XAxis dataKey="stage" tickLine={false} axisLine={{stroke:'#d4d4d8'}} tickMargin={12} padding={{left:32,right:32}}/>
        <YAxis tickLine={false} axisLine={false} tickMargin={8} width={64} domain={[0,1]} tickFormatter={value=>`${Math.round(value*100)}%`}/>
        <ChartTooltip cursor={false} isAnimationActive={false} content={<ChartTooltipContent labelFormatter={(_label,payload)=>`${payload[0]?.payload.stage} · ${payload[0]?.payload.version}`} formatter={value=><span>{percent(Number(value))}</span>}/>}/>
        <Line dataKey="score" type="linear" stroke="#5e6ad2" strokeWidth={1.8} connectNulls={false} isAnimationActive={false} dot={{r:5,fill:'#5e6ad2',stroke:'#fff',strokeWidth:2}} activeDot={{r:6}}/>
      </LineChart>
    </ChartContainer>
    <div className="ce-test-scores">{points.map(point=><span key={point.stage}>{point.stage}<strong>{point.score===null?'—':percent(point.score)}</strong></span>)}</div>
    {tests.selected?.reused_initial && <p className="ce-test-note">Initial Harness retained; its TEST result is reused.</p>}
  </div>;
}
