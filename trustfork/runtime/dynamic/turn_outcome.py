"""Single explicit outcome for history, T3 and late prefix."""
def turn_outcome(result,intent=None):
 stop=result['response']['stopReason']
 if stop=='length':return {'state':'resource_ended','reason':'output_limit'}
 if stop!='toolUse':return {'state':'completed'}
 ends=[e for e in result['events'] if e['type']=='tool_execution_end']
 if intent is not None and ends and ends[-1].get('toolName')=='wait_for_update' and not ends[-1].get('isError'):
  return intent
 return {'state':'continue'}
