import pytest
import json
from datetime import datetime, timedelta, timezone
import t_utilities as util
import pipeline_db as db
util.set_path_for_extract_modules()


def create_basic_database(db_factory, mock_db) -> dict:
	factory = db_factory(mock_db)
	return factory.create_mock_run(
		run_override={"pipeline_name": "basic_scenario"},
		players_per_task=factory.faker.random_int(1, 205),
	)

def test_basic_database_scenario(db_factory, mock_conn):
	result = create_basic_database(db_factory, mock_conn)
	assert result["run_id"] is not None
	assert len(result["player_task_ids"]) > 0
	assert len(result["mastery_task_ids"]) > 0
	assert len(result["player_ids"]) > 0

def create_failed_run_database(db_factory, mock_db) -> int:
	create_basic_database(db_factory, mock_db)
	factory = db_factory(mock_db)
	failed_run_id = factory.create_individual_run({"status": "failed", "error_message": "test error"})
	
	status_states = ["success", "failed", "in_progress", "pending"]
	for pt_status in status_states: #loop to simulate a player task for each status
		ptask_id = factory.create_individual_player_task({"run_id": failed_run_id, "status": pt_status})
  
		for id_length in range(1, 4): #loop to simulate players with different number of task ids
			for mt_status in status_states: #loop to simulate a mastery task for each player task, with the same status
				player_id = factory.get_uuid()
    
				if mt_status != "pending":
					mastery_task_id = factory.create_individual_mastery_task({"run_id": failed_run_id, "status": mt_status, "player_id": player_id})
				else:
					mastery_task_id = None
     
				player_task_ids = [ptask_id] #generate the player task ids based on loop count
				for fake in range(id_length-1):
					player_task_ids.insert(0, -(fake + 1)) #negative so no conflict with real autoincrement ids
     
				factory.create_individual_players_recorded({"player_task_ids": json.dumps(player_task_ids), "player_id": player_id, "mastery_status": mt_status, "mastery_task_id": mastery_task_id})
	
	return failed_run_id

def test_failed_run_scenario(db_factory, mock_conn):
	failed_run_id = create_failed_run_database(db_factory, mock_conn)
	
	db.cleanup_failed_run(failed_run_id, conn=mock_conn)
	
	# assert
	# all tasks for the failed run, that arent a success, should be set to failed
	# all records for those tasks should be set to failed or deleted (only delete if player_task_ids has only one task, and that task is failed)
	run_player_tasks = mock_conn.execute("SELECT task_id, status FROM player_tasks WHERE run_id = ?", (failed_run_id,)).fetchall()
	run_mastery_tasks = mock_conn.execute("SELECT task_id, status FROM mastery_tasks WHERE run_id = ?", (failed_run_id,)).fetchall()
 
	# assert that all player tasks for the failed run, that are not success, are set to failed
	for task_id, status in run_player_tasks:
		if status != "success":
			assert status == "failed"
			# assert that no record exists that only has this broken id as the player_task_ids
			assert len(mock_conn.execute("SELECT 1 FROM players_recorded WHERE player_task_ids = ?", (f"[{task_id}]",)).fetchall()) == 0
  
	for task_id, status in run_mastery_tasks:
		if status != "success":
			assert status == "failed"
			# assert that the record corresponding to this mastery task id, has its mastery_status set to failed
			assert len(mock_conn.execute("SELECT 1 FROM players_recorded WHERE mastery_task_id = ? AND mastery_status != 'failed'", (task_id,)).fetchall()) == 0
   
def test_cleanup_stale_runs(db_factory, mock_conn, monkeypatch):
	create_basic_database(db_factory, mock_conn)
	factory = db_factory(mock_conn)
	monkeypatch.setattr(db, "cleanup_failed_run", lambda *args, **kwargs: None)  # set cleanup_failed_run to nothing
 
	stale_run_id = factory.create_individual_run({"status": "running", "last_heartbeat": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()})
	active_run_id = factory.create_individual_run({"status": "running", "last_heartbeat": datetime.now(timezone.utc).isoformat()}, commit=True)
  
	db.cleanup_stale_runs(conn=mock_conn)
  
	stale_run_status = mock_conn.execute("SELECT status FROM runs WHERE run_id = ?", (stale_run_id,)).fetchone()[0]
	assert stale_run_status == "failed"
  
	active_run_status = mock_conn.execute("SELECT status FROM runs WHERE run_id = ?", (active_run_id,)).fetchone()[0]
	assert active_run_status == "running"